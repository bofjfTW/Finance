"""
Spot-Perpetual Arbitrage Agent
Calculates gross basis, costs, and net executable arbitrage edge.
"""
import time
from data.schema import FeatureSnapshot, AgentOutput
from agents.base import BaseAgent


class ArbitrageAgent(BaseAgent):
    def __init__(self, min_net_edge_bps: float = 15.0):
        super().__init__("arbitrage_agent")
        self.min_net_edge_bps = min_net_edge_bps

    def evaluate(self, snapshot: FeatureSnapshot) -> AgentOutput:
        symbol = snapshot.symbol
        reasons = []

        if not snapshot.is_valid or snapshot.spot_price <= 0 or snapshot.perp_price <= 0:
            return AgentOutput(
                agent_id=self.agent_id,
                symbol=symbol,
                score=0.0,
                confidence=0.0,
                risk=1.0,
                reason_codes=["NO_SPOT_PERP_PAIR"]
            )

        basis_bps = snapshot.basis_bps
        # Gross edge is absolute basis bps
        gross_edge_bps = abs(basis_bps)

        # Standard trading costs (Round trip taker fees 0.05% * 2 = 10 bps + slippage buffer ~ 4 bps)
        est_cost_bps = 14.0
        net_edge_bps = gross_edge_bps - est_cost_bps

        if net_edge_bps > self.min_net_edge_bps:
            # Positive net edge
            # If Perp > Spot (basis > 0): Short Perp + Long Spot
            # If Perp < Spot (basis < 0): Long Perp + Short Spot
            score = 1.0 if basis_bps < 0 else -1.0
            confidence = min(0.9, net_edge_bps / 50.0)
            risk = 0.35
            reasons.append(f"ARB_NET_EDGE_{round(net_edge_bps, 1)}_BPS")
        else:
            score = 0.0
            confidence = 0.3
            risk = 0.2
            reasons.append("NO_ARB_EDGE")

        return AgentOutput(
            agent_id=self.agent_id,
            symbol=symbol,
            score=score,
            confidence=confidence,
            risk=risk,
            timestamp=int(time.time() * 1000),
            ttl_ms=60000,
            reason_codes=reasons,
            metadata={"basis_bps": basis_bps, "net_edge_bps": net_edge_bps}
        )
