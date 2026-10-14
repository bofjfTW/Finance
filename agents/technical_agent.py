"""
Technical Agent
Computes directional momentum, multi-timeframe alignment, and breakout confirmation.
"""
import time
import numpy as np
from data.schema import FeatureSnapshot, AgentOutput
from agents.base import BaseAgent


class TechnicalAgent(BaseAgent):
    def __init__(self):
        super().__init__("technical_agent")

    def evaluate(self, snapshot: FeatureSnapshot) -> AgentOutput:
        symbol = snapshot.symbol
        reasons = []

        if not snapshot.is_valid:
            return AgentOutput(
                agent_id=self.agent_id,
                symbol=symbol,
                score=0.0,
                confidence=0.0,
                risk=0.8,
                reason_codes=["INVALID_SNAPSHOT"]
            )

        # Multi-timeframe momentum components
        m1 = np.clip(snapshot.return_1m * 100.0, -1.0, 1.0)
        m5 = np.clip(snapshot.return_5m * 50.0, -1.0, 1.0)
        m15 = np.clip(snapshot.return_15m * 30.0, -1.0, 1.0)
        m20 = np.clip(snapshot.return_20m * 25.0, -1.0, 1.0)

        # EMA slope score
        slope_score = np.clip(snapshot.ema_slope * 1000.0, -1.0, 1.0)

        # Weighted raw directional score
        raw_score = 0.15 * m1 + 0.30 * m5 + 0.30 * m15 + 0.15 * m20 + 0.10 * slope_score
        score = float(np.clip(raw_score, -1.0, 1.0))

        # Check alignment across timeframes
        alignments = [m5 > 0, m15 > 0, m20 > 0]
        if all(alignments):
            confidence = 0.85
            reasons.append("BULLISH_MTF_ALIGNMENT")
        elif not any(alignments):
            confidence = 0.85
            reasons.append("BEARISH_MTF_ALIGNMENT")
        else:
            confidence = 0.45
            reasons.append("MIXED_MTF_ALIGNMENT")

        # Volume confirmation boost
        if snapshot.volume_zscore > 1.5:
            confidence = min(0.95, confidence + 0.1)
            reasons.append("HIGH_VOLUME_EXPANSION")
        elif snapshot.volume_zscore < -1.0:
            confidence = max(0.2, confidence - 0.15)
            reasons.append("LOW_VOLUME_EXPANSION")

        # Volatility risk
        risk = float(np.clip(snapshot.realized_vol * 15.0, 0.1, 0.9))

        return AgentOutput(
            agent_id=self.agent_id,
            symbol=symbol,
            score=score,
            confidence=confidence,
            risk=risk,
            timestamp=int(time.time() * 1000),
            ttl_ms=1200000,
            reason_codes=reasons,
            metadata={"m5": m5, "m15": m15, "slope": slope_score}
        )
