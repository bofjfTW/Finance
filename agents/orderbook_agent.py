"""
Order Book Microstructure Agent
Evaluates short-term liquidity, book imbalance, spread, and adverse execution risk.
"""
import time
import numpy as np
from data.schema import FeatureSnapshot, AgentOutput
from agents.base import BaseAgent


class OrderBookAgent(BaseAgent):
    def __init__(self, max_spread_bps: float = 30.0):
        super().__init__("orderbook_agent")
        self.max_spread_bps = max_spread_bps

    def evaluate(self, snapshot: FeatureSnapshot) -> AgentOutput:
        symbol = snapshot.symbol
        reasons = []

        if not snapshot.is_valid:
            return AgentOutput(
                agent_id=self.agent_id,
                symbol=symbol,
                score=0.0,
                confidence=0.0,
                risk=1.0,
                reason_codes=["INVALID_ORDERBOOK"]
            )

        # Spread penalty
        spread_bps = snapshot.spread_bps
        if spread_bps > self.max_spread_bps:
            reasons.append("SPREAD_EXPLOSION")
            return AgentOutput(
                agent_id=self.agent_id,
                symbol=symbol,
                score=0.0,
                confidence=0.1,
                risk=0.95,
                reason_codes=reasons,
                metadata={"spread_bps": spread_bps}
            )

        # OBI (Order Book Imbalance)
        # OBI > 0 means more buyers on bids; OBI < 0 means more sellers on asks
        obi_score = 0.6 * snapshot.obi_5 + 0.4 * snapshot.obi_10

        # Microprice deviation
        # If microprice > mid_price, buyers are aggressive
        micro_score = np.clip(snapshot.microprice_deviation_bps / 5.0, -1.0, 1.0)

        # Combined microstructure score
        combined_score = float(np.clip(0.65 * obi_score + 0.35 * micro_score, -1.0, 1.0))

        # Confidence based on depth size
        total_depth_usd = snapshot.depth_bid_usd + snapshot.depth_ask_usd
        if total_depth_usd > 10000:
            confidence = 0.8
            reasons.append("DEEP_LIQUIDITY")
        elif total_depth_usd > 2000:
            confidence = 0.6
            reasons.append("MODERATE_LIQUIDITY")
        else:
            confidence = 0.35
            reasons.append("THIN_LIQUIDITY")

        # Risk is proportional to spread
        risk = float(np.clip(spread_bps / self.max_spread_bps, 0.1, 0.9))

        return AgentOutput(
            agent_id=self.agent_id,
            symbol=symbol,
            score=combined_score,
            confidence=confidence,
            risk=risk,
            timestamp=int(time.time() * 1000),
            ttl_ms=30000,  # Orderbook signals have fast 30s TTL
            reason_codes=reasons,
            metadata={"obi_5": snapshot.obi_5, "spread_bps": spread_bps}
        )
