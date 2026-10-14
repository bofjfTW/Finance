"""
Order Book Microstructure Features
"""
from typing import Tuple
from data.orderbook import OrderBook


def extract_orderbook_features(book: OrderBook) -> dict:
    if book.is_stale() or book.best_bid <= 0 or book.best_ask <= 0:
        return {
            "spread_bps": 999.0,
            "obi_5": 0.0,
            "obi_10": 0.0,
            "microprice_deviation_bps": 0.0,
            "depth_bid_usd": 0.0,
            "depth_ask_usd": 0.0,
            "is_valid": False
        }

    mid = book.mid_price
    spread_bps = book.spread_bps
    obi_5 = book.calculate_obi(5)
    obi_10 = book.calculate_obi(10)
    microprice = book.calculate_microprice()
    micro_dev_bps = ((microprice - mid) / mid) * 10000.0 if mid > 0 else 0.0

    depth_bid_usd = sum(p * q for p, q in book.bids[:10])
    depth_ask_usd = sum(p * q for p, q in book.asks[:10])

    return {
        "spread_bps": spread_bps,
        "obi_5": obi_5,
        "obi_10": obi_10,
        "microprice_deviation_bps": micro_dev_bps,
        "depth_bid_usd": depth_bid_usd,
        "depth_ask_usd": depth_ask_usd,
        "is_valid": True
    }
