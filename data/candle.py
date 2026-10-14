"""
Candle and OHLCV Aggregator
Supports 1m, 5m, 15m, 20m bars for technical feature engineering.
"""
from typing import List, Dict, Optional
from collections import deque
from data.schema import Candle, MarketType, TradeEvent


class CandleSeries:
    def __init__(self, symbol: str, interval: str = "1m", max_len: int = 500):
        self.symbol = symbol
        self.interval = interval
        self.max_len = max_len
        self.candles: deque[Candle] = deque(maxlen=max_len)
        self.current_candle: Optional[Candle] = None

    def add_candle(self, candle: Candle):
        """Append a completed or updated candle"""
        if self.candles and self.candles[-1].open_time == candle.open_time:
            self.candles[-1] = candle
        else:
            self.candles.append(candle)

    def on_trade(self, trade: TradeEvent):
        """Synthesize candles from live trade stream if klines are not streamed directly"""
        # Determine bar open time based on interval
        interval_ms = self._interval_to_ms(self.interval)
        bar_open_time = (trade.timestamp // interval_ms) * interval_ms
        bar_close_time = bar_open_time + interval_ms - 1

        if self.current_candle is None or self.current_candle.open_time != bar_open_time:
            if self.current_candle is not None:
                self.current_candle.is_closed = True
                self.candles.append(self.current_candle)

            self.current_candle = Candle(
                symbol=self.symbol,
                market_type=trade.market_type,
                interval=self.interval,
                open_time=bar_open_time,
                open=trade.price,
                high=trade.price,
                low=trade.price,
                close=trade.price,
                volume=trade.quantity,
                quote_volume=trade.price * trade.quantity,
                close_time=bar_close_time,
                is_closed=False
            )
        else:
            self.current_candle.high = max(self.current_candle.high, trade.price)
            self.current_candle.low = min(self.current_candle.low, trade.price)
            self.current_candle.close = trade.price
            self.current_candle.volume += trade.quantity
            self.current_candle.quote_volume += trade.price * trade.quantity

    def get_closes(self) -> List[float]:
        res = [c.close for c in self.candles]
        if self.current_candle:
            res.append(self.current_candle.close)
        return res

    def get_highs(self) -> List[float]:
        res = [c.high for c in self.candles]
        if self.current_candle:
            res.append(self.current_candle.high)
        return res

    def get_lows(self) -> List[float]:
        res = [c.low for c in self.candles]
        if self.current_candle:
            res.append(self.current_candle.low)
        return res

    def get_volumes(self) -> List[float]:
        res = [c.volume for c in self.candles]
        if self.current_candle:
            res.append(self.current_candle.volume)
        return res

    @staticmethod
    def _interval_to_ms(interval: str) -> int:
        if interval == "1m":
            return 60 * 1000
        elif interval == "5m":
            return 5 * 60 * 1000
        elif interval == "15m":
            return 15 * 60 * 1000
        elif interval == "20m":
            return 20 * 60 * 1000
        elif interval == "1h":
            return 60 * 60 * 1000
        return 60 * 1000
