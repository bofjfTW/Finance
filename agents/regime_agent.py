"""
Market Regime Agent
Determines: TRENDING_BULL, TRENDING_BEAR, RANGE, HIGH_VOLATILITY, SHOCK, ABNORMAL
"""
import time
from data.schema import FeatureSnapshot, AgentOutput, MarketRegime
from agents.base import BaseAgent


class MarketRegimeAgent(BaseAgent):
    def __init__(self):
        super().__init__("regime_agent")
        self.last_regimes = {}

    def evaluate(self, snapshot: FeatureSnapshot) -> AgentOutput:
        symbol = snapshot.symbol
        reasons = []

        if not snapshot.is_valid:
            regime = MarketRegime.ABNORMAL
            reasons.append("INVALID_DATA_OR_STALE")
            score = 0.0
            confidence = 0.1
            risk = 0.9
        elif snapshot.spread_bps > 35.0 or snapshot.realized_vol > 0.05:
            regime = MarketRegime.HIGH_VOLATILITY
            reasons.append("HIGH_SPREAD_OR_VOLATILITY")
            score = 0.0
            confidence = 0.7
            risk = 0.65
        elif abs(snapshot.return_20m) > 0.03:
            # Strong shock event
            regime = MarketRegime.SHOCK
            reasons.append("PRICE_SHOCK_DETECTED")
            score = 0.3 if snapshot.return_20m > 0 else -0.3
            confidence = 0.6
            risk = 0.75
        elif snapshot.ema_slope > 0.0005 and snapshot.return_5m > 0 and snapshot.return_15m > 0:
            regime = MarketRegime.TRENDING_BULL
            reasons.append("EMA_SLOPE_UP_AND_POSITIVE_RETURNS")
            score = 0.75
            confidence = 0.8
            risk = 0.25
        elif snapshot.ema_slope < -0.0005 and snapshot.return_5m < 0 and snapshot.return_15m < 0:
            regime = MarketRegime.TRENDING_BEAR
            reasons.append("EMA_SLOPE_DOWN_AND_NEGATIVE_RETURNS")
            score = -0.75
            confidence = 0.8
            risk = 0.25
        else:
            regime = MarketRegime.RANGE
            reasons.append("CONSOLIDATION_LOW_DIRECTIONAL_BIAS")
            score = 0.0
            confidence = 0.6
            risk = 0.35

        self.last_regimes[symbol] = regime

        return AgentOutput(
            agent_id=self.agent_id,
            symbol=symbol,
            score=score,
            confidence=confidence,
            risk=risk,
            timestamp=int(time.time() * 1000),
            ttl_ms=1200000,
            reason_codes=reasons,
            metadata={"regime": regime.value}
        )
