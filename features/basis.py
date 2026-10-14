"""
Spot-Perpetual Basis and Funding Feature Calculations
"""
from typing import Dict
from data.orderbook import OrderBook


def extract_basis_features(perp_book: OrderBook, spot_book: OrderBook) -> dict:
    p_mid = perp_book.mid_price
    s_mid = spot_book.mid_price

    if p_mid <= 0 or s_mid <= 0 or perp_book.is_stale() or spot_book.is_stale():
        return {
            "perp_price": p_mid,
            "spot_price": s_mid,
            "basis_bps": 0.0,
            "funding_rate": 0.0,
            "is_valid": False
        }

    # Basis = (P_perp - P_spot) / P_spot * 10,000 bps
    basis_bps = ((p_mid - s_mid) / s_mid) * 10000.0

    return {
        "perp_price": p_mid,
        "spot_price": s_mid,
        "basis_bps": basis_bps,
        "funding_rate": 0.0001,  # Default 0.01% standard funding baseline
        "is_valid": True
    }
