"""
Core System Unit Tests
Validates OrderBook, Features, Multi-Agent, Selector, Risk Gate, and Exit Monitor.
"""
import unittest
import time
from data.schema import (
    MarketType, OrderSide, PositionSide, StrategyType, MarketRegime,
    FeatureSnapshot, OpportunityEvaluation
)
from data.orderbook import OrderBook
from agents.regime_agent import MarketRegimeAgent
from agents.technical_agent import TechnicalAgent
from agents.orderbook_agent import OrderBookAgent
from agents.arbitrage_agent import ArbitrageAgent
from agents.selector import StrategySelector
from risk.risk_gate import RiskGate
from risk.kill_switch import KillSwitch
from execution.paper_broker import PaperBroker
from execution.exit_monitor import ContinuousExitMonitor


class TestQuantSystem(unittest.TestCase):

    def test_orderbook_metrics(self):
        ob = OrderBook("DOGE-USDT", MarketType.PERPETUAL)
        # Bids: [0.10, 100], [0.09, 200]
        # Asks: [0.11, 100], [0.12, 300]
        ob.update_snapshot(
            bids=[[0.10, 100.0], [0.09, 200.0]],
            asks=[[0.11, 100.0], [0.12, 300.0]],
            timestamp=int(time.time() * 1000)
        )
        self.assertEqual(ob.best_bid, 0.10)
        self.assertEqual(ob.best_ask, 0.11)
        self.assertAlmostEqual(ob.mid_price, 0.105)
        self.assertAlmostEqual(ob.spread, 0.01)
        self.assertFalse(ob.is_stale())
        # OBI top 2: bids sum = 300, asks sum = 400 -> (300-400)/(700) = -100/700 = -0.1428
        self.assertAlmostEqual(ob.calculate_obi(2), -100.0 / 700.0, places=3)

    def test_agents_and_selector(self):
        snap = FeatureSnapshot(
            symbol="DOGE-USDT",
            timestamp=int(time.time() * 1000),
            mid_price=0.10,
            return_1m=0.005,
            return_5m=0.015,
            return_15m=0.02,
            return_20m=0.025,
            ema_fast=0.101,
            ema_slow=0.098,
            ema_slope=0.001,
            atr_14=0.002,
            realized_vol=0.015,
            volume_zscore=2.0,
            spread_bps=8.0,
            obi_5=0.4,
            obi_10=0.35,
            microprice_deviation_bps=1.5,
            depth_bid_usd=12000.0,
            depth_ask_usd=8000.0,
            perp_price=0.10,
            spot_price=0.10,
            basis_bps=0.0,
            is_valid=True
        )

        regime_agent = MarketRegimeAgent()
        r_out = regime_agent.evaluate(snap)
        self.assertEqual(r_out.metadata["regime"], MarketRegime.TRENDING_BULL.value)

        tech_agent = TechnicalAgent()
        t_out = tech_agent.evaluate(snap)
        self.assertGreater(t_out.score, 0.0)  # Bullish

        selector = StrategySelector(["DOGE-USDT"], max_symbols=1)
        opp = selector.evaluate_symbol(snap)
        self.assertEqual(opp.strategy, StrategyType.MOMENTUM_LONG)
        self.assertTrue(opp.passed_validation)

    def test_risk_gate_sizing(self):
        kill_switch = KillSwitch()
        risk_gate = RiskGate(kill_switch=kill_switch, base_trade_risk=0.01, default_leverage=2)

        snap = FeatureSnapshot(
            symbol="DOGE-USDT",
            timestamp=int(time.time() * 1000),
            mid_price=0.10,
            realized_vol=0.01,
            spread_bps=5.0,
            is_valid=True
        )

        opp = OpportunityEvaluation(
            symbol="DOGE-USDT",
            strategy=StrategyType.MOMENTUM_LONG,
            opportunity_score=15.0,
            expected_edge_bps=30.0,
            confidence=0.8,
            risk_score=0.2,
            fee_bps=10.0,
            slippage_bps=4.0,
            net_edge_bps=16.0,
            passed_validation=True
        )

        decision = risk_gate.evaluate_proposal(opp, snap, account_equity=1000.0, current_positions={})
        self.assertTrue(decision.approved)
        self.assertGreater(decision.position_size, 0)
        self.assertEqual(decision.leverage, 2)
        # Margin should be bounded by equity
        self.assertLessEqual(decision.allocated_margin, 1000.0)

    def test_continuous_exit_monitor(self):
        broker = PaperBroker(initial_balance=1000.0)
        kill_switch = KillSwitch()
        monitor = ContinuousExitMonitor(
            broker=broker,
            kill_switch=kill_switch,
            soft_tp_roi=0.15,
            hard_tp_roi=0.30,
            soft_sl_roi=-0.05,
            hard_sl_roi=-0.10,
            trailing_callback_rate=0.03
        )

        # Open Long DOGE at 0.10, qty 10,000, margin 500 (2x leverage)
        pos = broker.open_position("DOGE-USDT", OrderSide.BUY, quantity=10000.0, price=0.10, leverage=2)
        self.assertIsNotNone(pos)

        # 1. Price unchanged -> hold
        broker.update_price("DOGE-USDT", 0.10)
        reason = monitor.check_position(pos, 0.10)
        self.assertIsNone(reason)

        # 2. Hard Take-Profit (+30% ROI):
        # 2x leverage -> +15% underlying price gain gives ~+30% net ROI
        broker.update_price("DOGE-USDT", 0.116)
        reason = monitor.check_position(pos, 0.116)
        self.assertIsNotNone(reason)
        self.assertIn("HARD_TAKE_PROFIT", reason)

        # 3. Trailing Stop test:
        # Reset position, price goes to 0.108 (+16% ROI), activates trailing stop, then drops to 0.106
        broker.positions["DOGE-USDT"].trailing_stop_active = False
        broker.positions["DOGE-USDT"].peak_roi = 0.0

        broker.update_price("DOGE-USDT", 0.1085)
        monitor.check_position(pos, 0.1085)
        self.assertTrue(pos.trailing_stop_active)

        # Drop price back to 0.1065 (ROI drops by > 3%)
        broker.update_price("DOGE-USDT", 0.1065)
        trail_reason = monitor.check_position(pos, 0.1065)
        self.assertIsNotNone(trail_reason)
        self.assertIn("TRAILING_STOP", trail_reason)

        # 4. Hard Stop Loss (-10% ROI):
        # Reset position and drop price to 0.0945 (down 5.5% on 2x leverage -> -11% ROI)
        pos.trailing_stop_active = False
        broker.update_price("DOGE-USDT", 0.0945)
        sl_reason = monitor.check_position(pos, 0.0945)
        self.assertIsNotNone(sl_reason)
        self.assertIn("HARD_STOP_LOSS", sl_reason)


if __name__ == "__main__":
    unittest.main()
