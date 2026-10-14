"""
Unified Feature Engine
Assembles point-in-time FeatureSnapshot across technical, orderbook, and basis features.
"""
import time
from data.schema import FeatureSnapshot, MarketType
from data.collector import DataCollector
from features.technical import (
    calculate_returns, calculate_ema, calculate_ema_slope,
    calculate_atr, calculate_realized_volatility, calculate_volume_zscore
)
from features.orderbook_features import extract_orderbook_features
from features.basis import extract_basis_features


class FeatureEngine:
    def __init__(self, collector: DataCollector):
        self.collector = collector

    def create_snapshot(self, symbol: str) -> FeatureSnapshot:
        perp_book = self.collector.get_orderbook(symbol, MarketType.PERPETUAL)
        spot_book = self.collector.get_orderbook(symbol, MarketType.SPOT)

        candles_1m = self.collector.candles_1m[symbol]
        candles_5m = self.collector.candles_5m[symbol]
        candles_15m = self.collector.candles_15m[symbol]
        candles_20m = self.collector.candles_20m[symbol]

        closes_1m = candles_1m.get_closes()
        highs_1m = candles_1m.get_highs()
        lows_1m = candles_1m.get_lows()
        volumes_1m = candles_1m.get_volumes()

        # If candles are not yet aggregated, fallback to current perp mid price
        mid_price = perp_book.mid_price
        if not closes_1m and mid_price > 0:
            closes_1m = [mid_price]
            highs_1m = [mid_price]
            lows_1m = [mid_price]
            volumes_1m = [100.0]

        # Returns
        ret_1m = calculate_returns(closes_1m, 1)
        ret_5m = calculate_returns(candles_5m.get_closes(), 1) or calculate_returns(closes_1m, 5)
        ret_15m = calculate_returns(candles_15m.get_closes(), 1) or calculate_returns(closes_1m, 15)
        ret_20m = calculate_returns(candles_20m.get_closes(), 1) or calculate_returns(closes_1m, 20)

        # Technical indicators
        ema_fast = calculate_ema(closes_1m, 9)
        ema_slow = calculate_ema(closes_1m, 21)
        ema_slope = calculate_ema_slope(closes_1m, 9, 3)
        atr_14 = calculate_atr(highs_1m, lows_1m, closes_1m, 14)
        r_vol = calculate_realized_volatility(closes_1m, 20)
        vol_zscore = calculate_volume_zscore(volumes_1m, 20)

        # Orderbook features
        ob_feats = extract_orderbook_features(perp_book)

        # Basis features
        basis_feats = extract_basis_features(perp_book, spot_book)

        is_valid = (
            ob_feats.get("is_valid", False) and
            mid_price > 0 and
            not perp_book.is_stale()
        )

        return FeatureSnapshot(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            mid_price=mid_price,
            return_1m=ret_1m,
            return_5m=ret_5m,
            return_15m=ret_15m,
            return_20m=ret_20m,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            ema_slope=ema_slope,
            atr_14=atr_14,
            realized_vol=r_vol,
            volume_zscore=vol_zscore,
            spread_bps=ob_feats["spread_bps"],
            obi_5=ob_feats["obi_5"],
            obi_10=ob_feats["obi_10"],
            microprice_deviation_bps=ob_feats["microprice_deviation_bps"],
            depth_bid_usd=ob_feats["depth_bid_usd"],
            depth_ask_usd=ob_feats["depth_ask_usd"],
            perp_price=basis_feats["perp_price"],
            spot_price=basis_feats["spot_price"],
            basis_bps=basis_feats["basis_bps"],
            funding_rate=basis_feats["funding_rate"],
            is_valid=is_valid
        )
