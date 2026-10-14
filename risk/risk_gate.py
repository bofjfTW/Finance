"""
Risk Gate & Dynamic Position Sizing
Implements 15 Risk Controls, highest veto power, and stop-distance sizing.
"""
import uuid
import time
import logging
from typing import Dict, List, Optional
from data.schema import OpportunityEvaluation, RiskDecision, PositionState, FeatureSnapshot
from risk.kill_switch import KillSwitch

logger = logging.getLogger("RiskGate")


class RiskGate:
    def __init__(
        self,
        kill_switch: KillSwitch,
        base_trade_risk: float = 0.01,
        dynamic_risk_min: float = 0.0025,
        dynamic_risk_max: float = 0.01,  # V1 Live hard cap 1.0%
        default_leverage: int = 2,
        max_leverage: int = 5,
        max_open_symbols: int = 2,
        max_drawdown_limit: float = 0.20,
        max_daily_loss: float = 0.05,
        max_consecutive_losses: int = 3,
        cooldown_periods: int = 3
    ):
        self.kill_switch = kill_switch
        self.base_trade_risk = base_trade_risk
        self.dynamic_risk_min = dynamic_risk_min
        self.dynamic_risk_max = dynamic_risk_max
        self.default_leverage = default_leverage
        self.max_leverage = max_leverage
        self.max_open_symbols = max_open_symbols
        self.max_drawdown_limit = max_drawdown_limit
        self.max_daily_loss = max_daily_loss
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_periods = cooldown_periods

        self.consecutive_loss_count = 0
        self.cooldown_remaining = 0
        self.daily_pnl = 0.0
        self.peak_equity = 1000.0

    def record_trade_result(self, pnl: float):
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_loss_count += 1
            if self.consecutive_loss_count >= self.max_consecutive_losses:
                self.cooldown_remaining = self.cooldown_periods
                logger.warning(f"Hit {self.consecutive_loss_count} consecutive losses. Pausing for {self.cooldown_periods} periods.")
        else:
            self.consecutive_loss_count = 0

    def on_window_tick(self):
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

    def evaluate_proposal(
        self,
        opp: OpportunityEvaluation,
        snapshot: FeatureSnapshot,
        account_equity: float,
        current_positions: Dict[str, PositionState]
    ) -> RiskDecision:
        decision_id = str(uuid.uuid4())[:8]

        # 1. Kill Switch Check
        if self.kill_switch.is_active:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason=f"KILL_SWITCH_ACTIVE: {self.kill_switch.reason}"
            )

        # 2. Stale or invalid data check
        if not snapshot.is_valid:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason="STALE_OR_INVALID_MARKET_DATA"
            )

        # 3. Drawdown Check
        if account_equity > self.peak_equity:
            self.peak_equity = account_equity
        current_drawdown = (self.peak_equity - account_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if current_drawdown >= self.max_drawdown_limit:
            self.kill_switch.trigger(f"DRAWDOWN_EXCEEDED_{round(current_drawdown*100, 1)}%")
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason="MAX_DRAWDOWN_LIMIT_EXCEEDED"
            )

        # 4. Daily Loss Limit Check
        daily_loss_pct = -self.daily_pnl / self.peak_equity if self.peak_equity > 0 else 0.0
        if daily_loss_pct >= self.max_daily_loss:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason=f"DAILY_LOSS_EXCEEDED_{round(daily_loss_pct*100, 1)}%"
            )

        # 5. Consecutive Loss Cooldown Check
        if self.cooldown_remaining > 0:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason=f"CONSECUTIVE_LOSS_COOLDOWN_ACTIVE_{self.cooldown_remaining}_LEFT"
            )

        # 6. Max Concurrent Symbols Check
        if len(current_positions) >= self.max_open_symbols and opp.symbol not in current_positions:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason=f"MAX_OPEN_SYMBOLS_REACHED_{self.max_open_symbols}"
            )

        # Already holding this symbol
        if opp.symbol in current_positions:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason="ALREADY_IN_POSITION"
            )

        # 7. Spread Explosion Check
        if snapshot.spread_bps > 30.0:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason=f"SPREAD_TOO_HIGH_{round(snapshot.spread_bps, 1)}_BPS"
            )

        # 8. Dynamic Risk and Position Sizing
        # Dynamic Risk formula: Base * Confidence * VolatilityDamping * DrawdownDamping
        conf_factor = opp.confidence
        vol_damping = max(0.6, 1.0 - min(snapshot.realized_vol * 10.0, 0.4))
        dd_damping = max(0.5, 1.0 - (current_drawdown / self.max_drawdown_limit))

        dynamic_risk = self.base_trade_risk * conf_factor * vol_damping * dd_damping
        dynamic_risk = max(self.dynamic_risk_min, min(dynamic_risk, self.dynamic_risk_max))

        # Dynamic Stop Loss selection (-5% to -10%)
        # In higher volatility, expand stop to -8% or -10% to prevent whipsaw
        if snapshot.realized_vol > 0.03:
            soft_sl_roi = -0.08
        else:
            soft_sl_roi = -0.05
        hard_sl_roi = -0.10

        leverage = min(self.default_leverage, self.max_leverage)

        # Distance on underlying price:
        # e.g., 2x leverage with -10% ROI stop -> price stop distance = 5.0%
        underlying_stop_pct = abs(hard_sl_roi) / leverage

        # Risk budget in USD
        risk_budget_usd = account_equity * dynamic_risk

        # Position notional = risk_budget / underlying_stop_pct
        target_notional_usd = risk_budget_usd / underlying_stop_pct

        # Cap notional by maximum leverage
        max_allowed_notional = account_equity * leverage
        notional_usd = min(target_notional_usd, max_allowed_notional)

        price = snapshot.mid_price
        if price <= 0:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason="INVALID_PRICE_FOR_SIZING"
            )

        position_size = notional_usd / price
        margin_required = notional_usd / leverage

        if margin_required > account_equity * 0.95:
            return RiskDecision(
                decision_id=decision_id,
                symbol=opp.symbol,
                approved=False,
                reason="INSUFFICIENT_AVAILABLE_MARGIN"
            )

        return RiskDecision(
            decision_id=decision_id,
            symbol=opp.symbol,
            approved=True,
            position_size=position_size,
            notional_usd=notional_usd,
            allocated_margin=margin_required,
            leverage=leverage,
            soft_stop_roi=soft_sl_roi,
            hard_stop_roi=hard_sl_roi,
            soft_tp_roi=0.15,
            hard_tp_roi=0.30,
            reason="APPROVED_BY_RISK_GATE"
        )
