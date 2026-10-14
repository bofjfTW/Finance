"""
Continuous Exit Monitor
Runs 24/7 independently of the 20-minute entry window.
Enforces:
  +15% soft take-profit activation & trailing stop
  +30% hard take-profit target
  -5% dynamic soft stop loss
  -10% hard stop loss limit
  Emergency risk veto / kill switch exits
"""
import logging
from typing import Dict, List, Optional, Callable
from data.schema import PositionState, PositionSide, MarketRegime
from execution.base import BaseBroker
from risk.kill_switch import KillSwitch

logger = logging.getLogger("ExitMonitor")


class ContinuousExitMonitor:
    def __init__(
        self,
        broker: BaseBroker,
        kill_switch: KillSwitch,
        soft_tp_roi: float = 0.15,
        hard_tp_roi: float = 0.30,
        soft_sl_roi: float = -0.05,
        hard_sl_roi: float = -0.10,
        trailing_callback_rate: float = 0.03,  # 3% callback from peak ROI
        on_exit_callback: Optional[Callable[[str, float, str], None]] = None
    ):
        self.broker = broker
        self.kill_switch = kill_switch
        self.soft_tp_roi = soft_tp_roi
        self.hard_tp_roi = hard_tp_roi
        self.soft_sl_roi = soft_sl_roi
        self.hard_sl_roi = hard_sl_roi
        self.trailing_callback_rate = trailing_callback_rate
        self.on_exit_callback = on_exit_callback

    def check_position(
        self,
        position: PositionState,
        current_price: float,
        current_regime: Optional[MarketRegime] = None
    ) -> Optional[str]:
        """
        Evaluate single position against exit rules.
        Returns exit reason string if position should be closed, or None to hold.
        """
        if current_price <= 0:
            return None

        # 1. Emergency Kill Switch Check
        if self.kill_switch.is_active:
            return f"KILL_SWITCH_EMERGENCY: {self.kill_switch.reason}"

        roi = position.net_roi

        # 2. Hard Take-Profit Target (>= +30%)
        if roi >= position.hard_tp_roi:
            return f"HARD_TAKE_PROFIT_TRIGGERED_{round(roi*100, 1)}%"

        # 3. Soft Take-Profit & Trailing Stop (+15% to +30%)
        if roi >= position.soft_tp_roi:
            if not position.trailing_stop_active:
                position.trailing_stop_active = True
                position.peak_roi = max(position.peak_roi, roi)
                logger.info(f"[TP-TARGET] {position.symbol} reached +15% ROI. Trailing stop ACTIVATED (Peak={position.peak_roi*100:.1f}%)")
            else:
                position.peak_roi = max(position.peak_roi, roi)

        if position.trailing_stop_active:
            drawdown_from_peak = position.peak_roi - roi
            if drawdown_from_peak >= self.trailing_callback_rate:
                return (
                    f"TRAILING_STOP_TRIGGERED (Peak={round(position.peak_roi*100, 1)}%, "
                    f"Exit={round(roi*100, 1)}%, Drawdown={round(drawdown_from_peak*100, 1)}%)"
                )

        # 4. Hard Stop Loss Limit (<= -10%)
        if roi <= position.hard_stop_roi:
            return f"HARD_STOP_LOSS_CAP_TRIGGERED_{round(roi*100, 1)}%"

        # 5. Dynamic Soft Stop Loss (-5% to -10%)
        if roi <= position.soft_stop_roi:
            # If market regime reverses or is in abnormal shock, exit early
            if current_regime in [MarketRegime.SHOCK, MarketRegime.ABNORMAL]:
                return f"SOFT_STOP_MARKET_SHOCK_{round(roi*100, 1)}%"
            if position.side == PositionSide.LONG and current_regime == MarketRegime.TRENDING_BEAR:
                return f"SOFT_STOP_REGIME_REVERSAL_BEAR_{round(roi*100, 1)}%"
            if position.side == PositionSide.SHORT and current_regime == MarketRegime.TRENDING_BULL:
                return f"SOFT_STOP_REGIME_REVERSAL_BULL_{round(roi*100, 1)}%"

        return None

    def evaluate_all_positions(
        self,
        prices: Dict[str, float],
        regimes: Optional[Dict[str, MarketRegime]] = None
    ) -> List[dict]:
        """Continuous exit loop iteration across all active positions"""
        positions = list(self.broker.get_positions().values())
        closed_reports = []

        for pos in positions:
            symbol = pos.symbol
            curr_price = prices.get(symbol, 0.0)
            regime = regimes.get(symbol) if regimes else None

            # Update broker internal unrealized values
            if hasattr(self.broker, "update_price"):
                self.broker.update_price(symbol, curr_price)

            exit_reason = self.check_position(pos, curr_price, regime)
            if exit_reason:
                pnl = self.broker.close_position(symbol, curr_price, exit_reason)
                closed_reports.append({
                    "symbol": symbol,
                    "pnl": pnl,
                    "reason": exit_reason
                })
                if self.on_exit_callback:
                    self.on_exit_callback(symbol, pnl, exit_reason)

        return closed_reports
