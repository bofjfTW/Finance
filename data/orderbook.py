"""
Order Book Builder and Microstructure Calculator
"""
import time
from typing import List, Tuple, Optional
from data.schema import OrderBookDepth, MarketType


class OrderBook:
    def __init__(self, symbol: str, market_type: MarketType = MarketType.PERPETUAL, max_depth: int = 20):
        self.symbol = symbol
        self.market_type = market_type
        self.max_depth = max_depth
        self.bids: List[List[float]] = []  # sorted descending by price [[price, qty], ...]
        self.asks: List[List[float]] = []  # sorted ascending by price [[price, qty], ...]
        self.last_update_ts: int = 0
        self.stale_timeout_sec: float = 15.0

    def update_snapshot(self, bids: List[List[float]], asks: List[List[float]], timestamp: Optional[int] = None):
        """Update full snapshot of the orderbook"""
        # Sort bids descending, asks ascending
        self.bids = sorted([[float(p), float(q)] for p, q in bids if float(q) > 0], key=lambda x: x[0], reverse=True)[:self.max_depth]
        self.asks = sorted([[float(p), float(q)] for p, q in asks if float(q) > 0], key=lambda x: x[0])[:self.max_depth]
        self.last_update_ts = timestamp or int(time.time() * 1000)

    def is_stale(self, current_ts: Optional[int] = None) -> bool:
        now = current_ts or int(time.time() * 1000)
        return (now - self.last_update_ts) > (self.stale_timeout_sec * 1000)

    @property
    def best_bid(self) -> float:
        return self.bids[0][0] if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0][0] if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        return self.best_bid or self.best_ask or 0.0

    @property
    def spread(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return max(0.0, self.best_ask - self.best_bid)
        return 0.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid > 0:
            return (self.spread / mid) * 10000.0
        return 0.0

    def calculate_obi(self, depth: int = 5) -> float:
        """
        Order Book Imbalance = (SumBid - SumAsk) / (SumBid + SumAsk)
        Range: -1.0 (all ask) to +1.0 (all bid)
        """
        b_vol = sum(q for _, q in self.bids[:depth])
        a_vol = sum(q for _, q in self.asks[:depth])
        total = b_vol + a_vol
        if total > 0:
            return (b_vol - a_vol) / total
        return 0.0

    def calculate_microprice(self) -> float:
        """
        Volume-weighted microprice at Top of Book
        P_micro = (BestBid * AskQty + BestAsk * BidQty) / (BidQty + AskQty)
        """
        if not self.bids or not self.asks:
            return self.mid_price
        bb_price, bb_qty = self.bids[0]
        ba_price, ba_qty = self.asks[0]
        total_qty = bb_qty + ba_qty
        if total_qty > 0:
            return (bb_price * ba_qty + ba_price * bb_qty) / total_qty
        return self.mid_price

    def to_depth_model(self) -> OrderBookDepth:
        return OrderBookDepth(
            symbol=self.symbol,
            market_type=self.market_type,
            timestamp=self.last_update_ts,
            bids=self.bids,
            asks=self.asks,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            spread=self.spread,
            spread_bps=self.spread_bps,
            obi=self.calculate_obi(5),
            microprice=self.calculate_microprice(),
            is_stale=self.is_stale()
        )
