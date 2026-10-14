"""
Paper Broker Simulation
Faithfully models execution fills, fees, margins, and position lifecycle.
"""
import time
import logging
from typing import Dict, Optional, List
from data.schema import PositionState, PositionSide, OrderSide, MarketType
from execution.base import BaseBroker

logger = logging.getLogger("PaperBroker")


class PaperBroker(BaseBroker):
    def __init__(
        self,
        initial_balance: float = 1000.0,
        taker_fee_rate: float = 0.0005,
        maker_fee_rate: float = 0.0002
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance  # Realized cash
        self.taker_fee_rate = taker_fee_rate
        self.maker_fee_rate = maker_fee_rate

        self.positions: Dict[str, PositionState] = {}
        self.trade_history: List[dict] = []

    def get_equity(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.balance + unrealized

    def get_available_balance(self) -> float:
        locked_margin = sum(p.margin for p in self.positions.values())
        return max(0.0, self.get_equity() - locked_margin)

    def get_positions(self) -> Dict[str, PositionState]:
        return self.positions

    def open_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        leverage: int = 2,
        market_type: MarketType = MarketType.PERPETUAL,
        trace_id: str = ""
    ) -> Optional[PositionState]:
        if symbol in self.positions:
            logger.warning(f"Position for {symbol} already exists. Cannot open new.")
            return None

        # Slippage: taker orders cross half spread (~2 bps)
        slippage_mult = 1.0002 if side == OrderSide.BUY else 0.9998
        fill_price = price * slippage_mult
        notional = fill_price * quantity
        margin = notional / leverage

        # Taker fee
        fee = notional * self.taker_fee_rate
        self.balance -= fee

        pos_side = PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT

        pos = PositionState(
            symbol=symbol,
            market_type=market_type,
            side=pos_side,
            entry_price=fill_price,
            current_price=fill_price,
            quantity=quantity,
            margin=margin,
            leverage=leverage,
            unrealized_pnl=0.0,
            net_roi=0.0,
            underlying_return=0.0,
            peak_roi=0.0,
            trailing_stop_active=False,
            soft_stop_roi=-0.05,
            hard_stop_roi=-0.10,
            soft_tp_roi=0.15,
            hard_tp_roi=0.30,
            entry_time=int(time.time() * 1000),
            last_update_time=int(time.time() * 1000),
            trace_id=trace_id
        )

        self.positions[symbol] = pos
        logger.info(
            f"[OPEN] {pos_side.value} {symbol}: Qty={quantity:.4f}, Price={fill_price:.5f}, "
            f"Notional=${notional:.2f}, Margin=${margin:.2f}, Fee=${fee:.4f}"
        )
        return pos

    def update_price(self, symbol: str, current_price: float):
        """Update unrealized PnL and net leveraged ROI in real time"""
        pos = self.positions.get(symbol)
        if not pos or current_price <= 0:
            return

        pos.current_price = current_price
        pos.last_update_time = int(time.time() * 1000)

        # Calculate underlying return
        if pos.side == PositionSide.LONG:
            ret = (current_price - pos.entry_price) / pos.entry_price
        else:
            ret = (pos.entry_price - current_price) / pos.entry_price

        pos.underlying_return = ret
        notional = pos.entry_price * pos.quantity

        # Gross unrealized PnL
        gross_pnl = notional * ret
        # Deduct estimated exit taker fee for true net PnL
        exit_fee = (current_price * pos.quantity) * self.taker_fee_rate
        pos.unrealized_pnl = gross_pnl - exit_fee

        # Net Leveraged ROI = (unrealized_pnl / margin)
        pos.net_roi = pos.unrealized_pnl / pos.margin if pos.margin > 0 else 0.0

        # Update peak ROI for trailing stop
        if pos.net_roi > pos.peak_roi:
            pos.peak_roi = pos.net_roi

    def close_position(
        self,
        symbol: str,
        price: float,
        reason: str = "MANUAL"
    ) -> Optional[float]:
        pos = self.positions.get(symbol)
        if not pos:
            return None

        # Slippage on exit
        slippage_mult = 0.9998 if pos.side == PositionSide.LONG else 1.0002
        exit_price = price * slippage_mult

        if pos.side == PositionSide.LONG:
            ret = (exit_price - pos.entry_price) / pos.entry_price
        else:
            ret = (pos.entry_price - exit_price) / pos.entry_price

        notional_entry = pos.entry_price * pos.quantity
        notional_exit = exit_price * pos.quantity

        gross_pnl = notional_entry * ret
        exit_fee = notional_exit * self.taker_fee_rate
        net_pnl = gross_pnl - exit_fee

        # Realize PnL
        self.balance += (pos.margin + net_pnl)
        realized_roi = net_pnl / pos.margin if pos.margin > 0 else 0.0

        trade_record = {
            "symbol": symbol,
            "side": pos.side.value,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "quantity": pos.quantity,
            "margin": pos.margin,
            "leverage": pos.leverage,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "roi": realized_roi,
            "duration_sec": (int(time.time() * 1000) - pos.entry_time) / 1000.0,
            "reason": reason,
            "trace_id": pos.trace_id,
            "timestamp": int(time.time() * 1000)
        }
        self.trade_history.append(trade_record)
        del self.positions[symbol]

        pnl_symbol = "[CLOSE+]" if net_pnl >= 0 else "[CLOSE-]"
        logger.info(
            f"{pnl_symbol} {pos.side.value} {symbol}: Price={exit_price:.5f}, "
            f"Net PnL=${net_pnl:.2f} ({realized_roi*100:.1f}%), Reason={reason}"
        )
        return net_pnl
