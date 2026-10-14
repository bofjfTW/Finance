"""
Backtest Engine
Simulates 20-min Entry Gate and Continuous TP/SL Exit Monitor over multi-asset historical bars.
"""
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from data.schema import (
    FeatureSnapshot, OrderSide, PositionSide, MarketType,
    StrategyType
)
from data.orderbook import OrderBook
from agents.selector import StrategySelector
from risk.risk_gate import RiskGate
from risk.kill_switch import KillSwitch
from execution.paper_broker import PaperBroker
from execution.exit_monitor import ContinuousExitMonitor
from backtest.metrics import calculate_metrics


class BacktestEngine:
    def __init__(
        self,
        symbols: List[str] = None,
        initial_balance: float = 1000.0,
        leverage: int = 2,
        soft_tp_roi: float = 0.15,
        hard_tp_roi: float = 0.30,
        soft_sl_roi: float = -0.05,
        hard_sl_roi: float = -0.10
    ):
        self.symbols = symbols or ["DOGE-USDT", "PEPE-USDT", "WIF-USDT", "BONK-USDT"]
        self.initial_balance = initial_balance
        self.leverage = leverage

        self.kill_switch = KillSwitch()
        self.broker = PaperBroker(initial_balance=initial_balance)
        self.selector = StrategySelector(self.symbols, max_symbols=2)
        self.risk_gate = RiskGate(
            kill_switch=self.kill_switch,
            base_trade_risk=0.01,
            default_leverage=leverage,
            max_open_symbols=2
        )
        self.exit_monitor = ContinuousExitMonitor(
            broker=self.broker,
            kill_switch=self.kill_switch,
            soft_tp_roi=soft_tp_roi,
            hard_tp_roi=hard_tp_roi,
            soft_sl_roi=soft_sl_roi,
            hard_sl_roi=hard_sl_roi
        )

        self.equity_curve: List[float] = [initial_balance]

    def run_simulation(self, price_data: Dict[str, pd.DataFrame]) -> dict:
        """
        Runs backtest over price_data dictionary: {symbol: df_with_ohlcv}
        df columns required: open, high, low, close, volume
        """
        # Align timestamps across all symbols
        common_index = None
        for sym, df in price_data.items():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)

        if common_index is None or len(common_index) < 30:
            raise ValueError("Insufficient overlapping price data across symbols for backtest")

        bar_count = len(common_index)

        for i in range(25, bar_count):
            curr_idx = common_index[i]

            # 1. Update prices & check continuous exits on every bar
            current_prices = {sym: float(price_data[sym].loc[curr_idx, "close"]) for sym in self.symbols}
            self.exit_monitor.evaluate_all_positions(current_prices)

            # 2. 20-minute Entry Decision Window (e.g. every bar if bars are 20m, or every 4 bars if 5m)
            # Evaluate feature snapshots for each symbol
            snapshots = {}
            for sym in self.symbols:
                df_slice = price_data[sym].iloc[:i+1]
                closes = df_slice["close"].values
                highs = df_slice["high"].values
                lows = df_slice["low"].values
                vols = df_slice["volume"].values

                ret_1m = (closes[-1] - closes[-2]) / closes[-2] if len(closes) > 1 else 0.0
                ret_5m = (closes[-1] - closes[-6]) / closes[-6] if len(closes) > 5 else 0.0
                ret_15m = (closes[-1] - closes[-16]) / closes[-16] if len(closes) > 15 else 0.0
                ret_20m = (closes[-1] - closes[-21]) / closes[-21] if len(closes) > 20 else 0.0

                ema_fast = float(pd.Series(closes).ewm(span=9).mean().iloc[-1])
                ema_slow = float(pd.Series(closes).ewm(span=21).mean().iloc[-1])
                slope = (ema_fast - closes[-3]) / (closes[-3] * 3) if closes[-3] > 0 else 0.0

                r_vol = float(np.std(np.diff(closes[-20:]) / closes[-20:-1])) if len(closes) > 20 else 0.01

                # Mock orderbook depth from bar volume and close price
                spread_bps = 5.0 + (r_vol * 200.0)
                obi_5 = float(np.clip(ret_1m * 50.0, -0.8, 0.8))

                snapshots[sym] = FeatureSnapshot(
                    symbol=sym,
                    timestamp=int(curr_idx.timestamp() * 1000) if hasattr(curr_idx, "timestamp") else i * 60000,
                    mid_price=float(closes[-1]),
                    return_1m=float(ret_1m),
                    return_5m=float(ret_5m),
                    return_15m=float(ret_15m),
                    return_20m=float(ret_20m),
                    ema_fast=ema_fast,
                    ema_slow=ema_slow,
                    ema_slope=float(slope),
                    atr_14=float(r_vol * closes[-1]),
                    realized_vol=r_vol,
                    volume_zscore=0.5,
                    spread_bps=spread_bps,
                    obi_5=obi_5,
                    obi_10=obi_5 * 0.8,
                    microprice_deviation_bps=obi_5 * 2.0,
                    depth_bid_usd=15000.0,
                    depth_ask_usd=15000.0,
                    perp_price=float(closes[-1]),
                    spot_price=float(closes[-1]) * 0.9999,
                    basis_bps=1.0,
                    is_valid=True
                )

            # Evaluate strategy selector across 4 coins
            evaluations = self.selector.scan_all_symbols(snapshots)
            self.risk_gate.on_window_tick()

            # Execute approved opportunities
            account_equity = self.broker.get_equity()
            for opp in evaluations:
                if opp.passed_validation and opp.strategy in [StrategyType.MOMENTUM_LONG, StrategyType.MOMENTUM_SHORT]:
                    risk_dec = self.risk_gate.evaluate_proposal(
                        opp=opp,
                        snapshot=snapshots[opp.symbol],
                        account_equity=account_equity,
                        current_positions=self.broker.get_positions()
                    )

                    if risk_dec.approved and risk_dec.position_size > 0:
                        side = OrderSide.BUY if opp.strategy == StrategyType.MOMENTUM_LONG else OrderSide.SELL
                        self.broker.open_position(
                            symbol=opp.symbol,
                            side=side,
                            quantity=risk_dec.position_size,
                            price=snapshots[opp.symbol].mid_price,
                            leverage=risk_dec.leverage,
                            trace_id=f"bt_trade_{i}"
                        )

            # Record equity
            self.equity_curve.append(self.broker.get_equity())

        # Close any lingering open positions at final bar
        final_prices = {sym: float(price_data[sym].loc[common_index[-1], "close"]) for sym in self.symbols}
        for pos in list(self.broker.get_positions().values()):
            self.broker.close_position(pos.symbol, final_prices[pos.symbol], reason="BACKTEST_END")

        self.equity_curve.append(self.broker.get_equity())

        metrics = calculate_metrics(
            initial_equity=self.initial_balance,
            equity_curve=self.equity_curve,
            trade_history=self.broker.trade_history
        )
        return metrics
