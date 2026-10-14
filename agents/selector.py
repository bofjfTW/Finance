"""
Strategy Selector and Opportunity Ranker
Performs 20-minute Entry Decision, Hierarchical Fusion, and selects Best 1-2 coins.
"""
from typing import List, Dict, Tuple, Optional
import time
from data.schema import (
    FeatureSnapshot, AgentOutput, StrategyType, MarketRegime,
    OpportunityEvaluation
)
from agents.regime_agent import MarketRegimeAgent
from agents.technical_agent import TechnicalAgent
from agents.orderbook_agent import OrderBookAgent
from agents.arbitrage_agent import ArbitrageAgent


class StrategySelector:
    def __init__(
        self,
        symbols: List[str],
        max_symbols: int = 2,
        min_net_edge_bps: float = 8.0,
        fee_bps: float = 10.0,
        est_slippage_bps: float = 4.0
    ):
        self.symbols = symbols
        self.max_symbols = max_symbols
        self.min_net_edge_bps = min_net_edge_bps
        self.fee_bps = fee_bps
        self.est_slippage_bps = est_slippage_bps

        self.regime_agent = MarketRegimeAgent()
        self.technical_agent = TechnicalAgent()
        self.orderbook_agent = OrderBookAgent()
        self.arbitrage_agent = ArbitrageAgent()

    def evaluate_symbol(self, snapshot: FeatureSnapshot) -> OpportunityEvaluation:
        """Run all 4 agents on a symbol snapshot and fuse decisions"""
        regime_out = self.regime_agent.evaluate(snapshot)
        tech_out = self.technical_agent.evaluate(snapshot)
        ob_out = self.orderbook_agent.evaluate(snapshot)
        arb_out = self.arbitrage_agent.evaluate(snapshot)

        regime_val = regime_out.metadata.get("regime", MarketRegime.RANGE.value)

        # 1. Check if abnormal or extreme risk
        if regime_val == MarketRegime.ABNORMAL.value or not snapshot.is_valid:
            return OpportunityEvaluation(
                symbol=snapshot.symbol,
                strategy=StrategyType.NO_TRADE,
                opportunity_score=-100.0,
                expected_edge_bps=0.0,
                confidence=0.0,
                risk_score=1.0,
                fee_bps=self.fee_bps,
                slippage_bps=self.est_slippage_bps,
                net_edge_bps=-100.0,
                passed_validation=False,
                rejection_reason="ABNORMAL_REGIME_OR_STALE"
            )

        # 2. Check Arbitrage opportunity
        if arb_out.metadata.get("net_edge_bps", 0.0) > 15.0:
            net_edge = arb_out.metadata["net_edge_bps"]
            score = (net_edge * arb_out.confidence) / max(0.2, arb_out.risk)
            return OpportunityEvaluation(
                symbol=snapshot.symbol,
                strategy=StrategyType.SPOT_PERP_ARBITRAGE,
                opportunity_score=score,
                expected_edge_bps=net_edge + self.fee_bps + self.est_slippage_bps,
                confidence=arb_out.confidence,
                risk_score=arb_out.risk,
                fee_bps=self.fee_bps,
                slippage_bps=self.est_slippage_bps,
                net_edge_bps=net_edge,
                passed_validation=True
            )

        # 3. Hierarchical Directional Momentum Fusion
        # Technical provides primary direction (weight 0.65), OrderBook provides timing & confirmation (weight 0.35)
        fused_direction = 0.65 * tech_out.score + 0.35 * ob_out.score
        fused_confidence = 0.60 * tech_out.confidence + 0.40 * ob_out.confidence
        fused_risk = max(tech_out.risk, ob_out.risk)

        # Regime modifier
        if regime_val == MarketRegime.TRENDING_BULL.value:
            if fused_direction > 0:
                fused_confidence = min(0.95, fused_confidence + 0.15)
        elif regime_val == MarketRegime.TRENDING_BEAR.value:
            if fused_direction < 0:
                fused_confidence = min(0.95, fused_confidence + 0.15)
        elif regime_val == MarketRegime.RANGE.value:
            fused_confidence *= 0.7  # Damped in ranging chop

        # Expected gross edge in basis points (scaled by direction strength and volatility)
        vol_factor = max(1.0, snapshot.realized_vol * 100.0)
        expected_edge_bps = abs(fused_direction) * vol_factor * 30.0

        # Net edge after deducting taker fees, spread crossing slippage, and funding buffer
        total_cost_bps = self.fee_bps + max(self.est_slippage_bps, snapshot.spread_bps * 0.5)
        net_edge_bps = expected_edge_bps - total_cost_bps

        # Formula from doc1 (Line 159):
        # Opportunity_i = (ExpectedEdge_i * Confidence_i) / Risk_i - TotalCosts
        opportunity_score = (expected_edge_bps * fused_confidence) / max(0.15, fused_risk) - total_cost_bps

        passed = net_edge_bps >= self.min_net_edge_bps and fused_confidence >= 0.50

        if not passed:
            strategy = StrategyType.NO_TRADE
            rejection = "INSUFFICIENT_NET_EDGE_OR_CONFIDENCE"
        elif fused_direction > 0.15:
            strategy = StrategyType.MOMENTUM_LONG
            rejection = None
        elif fused_direction < -0.15:
            strategy = StrategyType.MOMENTUM_SHORT
            rejection = None
        else:
            strategy = StrategyType.NO_TRADE
            passed = False
            rejection = "NEUTRAL_SIGNAL"

        return OpportunityEvaluation(
            symbol=snapshot.symbol,
            strategy=strategy,
            opportunity_score=opportunity_score if passed else -10.0,
            expected_edge_bps=expected_edge_bps,
            confidence=fused_confidence,
            risk_score=fused_risk,
            fee_bps=self.fee_bps,
            slippage_bps=max(self.est_slippage_bps, snapshot.spread_bps * 0.5),
            net_edge_bps=net_edge_bps,
            passed_validation=passed,
            rejection_reason=rejection
        )

    def scan_all_symbols(self, snapshots: Dict[str, FeatureSnapshot]) -> List[OpportunityEvaluation]:
        """
        Scan all 4 coins (DOGE, PEPE, WIF, BONK), rank by opportunity score,
        and select top 1-2 best opportunities.
        """
        evaluations: List[OpportunityEvaluation] = []
        for symbol in self.symbols:
            snap = snapshots.get(symbol)
            if snap:
                eval_res = self.evaluate_symbol(snap)
                evaluations.append(eval_res)

        # Sort descending by opportunity_score
        evaluations.sort(key=lambda x: x.opportunity_score, reverse=True)

        # Assign ranks
        for idx, ev in enumerate(evaluations):
            ev.rank = idx + 1

        # Only allow top max_symbols that passed validation
        passed_count = 0
        final_list = []
        for ev in evaluations:
            if ev.passed_validation and passed_count < self.max_symbols:
                passed_count += 1
                final_list.append(ev)
            else:
                # If not selected in top 1-2, mark as NO_TRADE
                if ev.passed_validation:
                    ev.passed_validation = False
                    ev.strategy = StrategyType.NO_TRADE
                    ev.rejection_reason = "EXCEEDED_MAX_CONCURRENT_SYMBOLS"
                final_list.append(ev)

        return final_list
