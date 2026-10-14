"""
Real-Time Market Data Collector and State Manager
Coordinates OrderBooks, Trades, OHLCV, and Data Quality Monitoring
"""
import time
import logging
from typing import Dict, List, Optional, Callable, Any
from data.schema import MarketType, OrderBookDepth, TradeEvent, Candle, FeatureSnapshot
from data.orderbook import OrderBook
from data.candle import CandleSeries
from exchange.bingx.ws import BingXWebSocketClient

logger = logging.getLogger("DataCollector")


class DataCollector:
    def __init__(self, symbols: List[str], symbol_config: Dict[str, Dict[str, Any]]):
        self.symbols = symbols
        self.symbol_config = symbol_config
        # Perpetual and Spot OrderBooks
        self.perp_books: Dict[str, OrderBook] = {
            s: OrderBook(s, MarketType.PERPETUAL, max_depth=20) for s in symbols
        }
        self.spot_books: Dict[str, OrderBook] = {
            s: OrderBook(s, MarketType.SPOT, max_depth=20) for s in symbols
        }
        # Multi-timeframe Candle series (1m, 5m, 15m, 20m)
        self.candles_1m: Dict[str, CandleSeries] = {s: CandleSeries(s, "1m") for s in symbols}
        self.candles_5m: Dict[str, CandleSeries] = {s: CandleSeries(s, "5m") for s in symbols}
        self.candles_15m: Dict[str, CandleSeries] = {s: CandleSeries(s, "15m") for s in symbols}
        self.candles_20m: Dict[str, CandleSeries] = {s: CandleSeries(s, "20m") for s in symbols}

        self.last_trade_events: Dict[str, TradeEvent] = {}
        self.trade_counts: Dict[str, int] = {s: 0 for s in symbols}
        self.ws_client: Optional[BingXWebSocketClient] = None
        self.stale_threshold_sec: float = 15.0

    def start_live_feed(self):
        """Initialize and start BingX WebSocket client"""
        self.ws_client = BingXWebSocketClient(
            symbol_map=self.symbol_config,
            on_orderbook=self.on_orderbook_update,
            on_trade=self.on_trade_update,
            on_kline=self.on_kline_update
        )
        return self.ws_client.start()

    def on_orderbook_update(
        self, symbol: str, market_type: MarketType, bids: List[List[float]], asks: List[List[float]], timestamp: int
    ):
        if symbol not in self.symbols:
            return
        if market_type == MarketType.PERPETUAL:
            self.perp_books[symbol].update_snapshot(bids, asks, timestamp)
        else:
            self.spot_books[symbol].update_snapshot(bids, asks, timestamp)

    def on_trade_update(self, trade: TradeEvent):
        symbol = trade.symbol
        if symbol not in self.symbols:
            return
        self.last_trade_events[symbol] = trade
        self.trade_counts[symbol] += 1
        # Update multi-timeframe candles
        self.candles_1m[symbol].on_trade(trade)
        self.candles_5m[symbol].on_trade(trade)
        self.candles_15m[symbol].on_trade(trade)
        self.candles_20m[symbol].on_trade(trade)

    def on_kline_update(self, symbol: str, market_type: MarketType, interval: str, msg: dict):
        if symbol not in self.symbols:
            return
        data = msg.get("data", [])
        if isinstance(data, list) and len(data) > 0:
            k = data[0]
            candle = Candle(
                symbol=symbol,
                market_type=market_type,
                interval=interval,
                open_time=int(k.get("T", time.time() * 1000)),
                open=float(k.get("o", 0)),
                high=float(k.get("h", 0)),
                low=float(k.get("l", 0)),
                close=float(k.get("c", 0)),
                volume=float(k.get("v", 0)),
                quote_volume=float(k.get("c", 0)) * float(k.get("v", 0)),
                close_time=int(k.get("T", time.time() * 1000)) + 60000,
                is_closed=False
            )
            if interval == "1m":
                self.candles_1m[symbol].add_candle(candle)

    def get_orderbook(self, symbol: str, market_type: MarketType = MarketType.PERPETUAL) -> OrderBook:
        if market_type == MarketType.PERPETUAL:
            return self.perp_books[symbol]
        return self.spot_books[symbol]

    def is_symbol_healthy(self, symbol: str) -> bool:
        """Check if perpetual orderbook is not stale and has depth"""
        book = self.perp_books.get(symbol)
        if not book:
            return False
        if book.is_stale() or book.best_bid <= 0 or book.best_ask <= 0:
            return False
        return True

    def get_health_status(self) -> Dict[str, dict]:
        status = {}
        now = int(time.time() * 1000)
        for s in self.symbols:
            p_book = self.perp_books[s]
            status[s] = {
                "perp_price": p_book.mid_price,
                "spread_bps": round(p_book.spread_bps, 2),
                "obi_5": round(p_book.calculate_obi(5), 3),
                "trades_count": self.trade_counts[s],
                "is_stale": p_book.is_stale(now),
                "age_ms": now - p_book.last_update_ts if p_book.last_update_ts > 0 else -1
            }
        return status
