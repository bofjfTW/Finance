"""
BingX WebSocket Client with GZIP Decompression, Ping/Pong Heartbeat, and Resilient Reconnect
"""
import asyncio
import gzip
import json
import logging
import ssl
import time
from typing import Dict, Any, Callable, Optional, List
import certifi
import websockets
from data.schema import MarketType, OrderSide, TradeEvent

logger = logging.getLogger("BingXWS")


class BingXWebSocketClient:
    def __init__(
        self,
        perp_ws_url: str = "wss://open-api-swap.bingx.com/swap-market",
        spot_ws_url: str = "wss://open-api-ws.bingx.com/market",
        symbol_map: Optional[Dict[str, Dict[str, str]]] = None,
        on_orderbook: Optional[Callable[[str, MarketType, List[List[float]], List[List[float]], int], None]] = None,
        on_trade: Optional[Callable[[TradeEvent], None]] = None,
        on_kline: Optional[Callable[[str, MarketType, str, Dict[str, Any]], None]] = None,
    ):
        self.perp_ws_url = perp_ws_url
        self.spot_ws_url = spot_ws_url
        self.symbol_map = symbol_map or {}
        # Reverse mappings: exchange_symbol -> standard_symbol (e.g., '1000PEPE-USDT' -> 'PEPE-USDT')
        self.perp_to_standard: Dict[str, str] = {}
        self.spot_to_standard: Dict[str, str] = {}
        for std_sym, info in self.symbol_map.items():
            self.perp_to_standard[info.get("bingx_perp_symbol", std_sym)] = std_sym
            self.spot_to_standard[info.get("bingx_spot_symbol", std_sym)] = std_sym

        self.on_orderbook = on_orderbook
        self.on_trade = on_trade
        self.on_kline = on_kline

        self.running = False
        self.reconnect_count = 0
        self.last_msg_ts = 0
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def start(self):
        """Start both perpetual and spot WebSocket streams"""
        self.running = True
        logger.info("Starting BingX WebSocket clients...")
        await asyncio.gather(
            self._run_perp_stream(),
            self._run_spot_stream(),
            return_exceptions=True
        )

    def stop(self):
        self.running = False

    async def _run_perp_stream(self):
        """USDT-M Perpetual stream loop"""
        backoff = 1.0
        while self.running:
            try:
                logger.info(f"Connecting to Perpetual WS: {self.perp_ws_url}")
                async with websockets.connect(self.perp_ws_url, ssl=self.ssl_context, ping_interval=None) as ws:
                    backoff = 1.0
                    logger.info("Perpetual WS connected. Subscribing to channels...")

                    # Subscribe for each symbol: depth, trade, kline
                    for std_sym, info in self.symbol_map.items():
                        perp_sym = info.get("bingx_perp_symbol", std_sym)
                        # Subscribe depth20
                        await ws.send(json.dumps({
                            "id": f"sub_depth_{perp_sym}",
                            "reqType": "sub",
                            "dataType": f"{perp_sym}@depth20"
                        }))
                        # Subscribe trade
                        await ws.send(json.dumps({
                            "id": f"sub_trade_{perp_sym}",
                            "reqType": "sub",
                            "dataType": f"{perp_sym}@trade"
                        }))
                        # Subscribe 1m kline
                        await ws.send(json.dumps({
                            "id": f"sub_kline_{perp_sym}",
                            "reqType": "sub",
                            "dataType": f"{perp_sym}@kline_1m"
                        }))

                    while self.running:
                        raw = await ws.recv()
                        self.last_msg_ts = int(time.time() * 1000)
                        if isinstance(raw, bytes):
                            text = gzip.decompress(raw).decode("utf-8")
                        else:
                            text = raw

                        if text == "Ping":
                            await ws.send("Pong")
                            continue

                        try:
                            data = json.loads(text)
                            await self._handle_perp_message(data)
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                self.reconnect_count += 1
                logger.warning(f"Perpetual WS disconnected ({e}), reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    async def _handle_perp_message(self, msg: Dict[str, Any]):
        dtype = msg.get("dataType", "")
        if not dtype:
            return

        parts = dtype.split("@")
        if len(parts) != 2:
            return
        exch_sym, channel = parts
        std_sym = self.perp_to_standard.get(exch_sym, exch_sym)

        if channel == "depth20" and "data" in msg:
            depth_data = msg["data"]
            if depth_data and self.on_orderbook:
                bids = depth_data.get("bids", [])
                asks = depth_data.get("asks", [])
                ts = msg.get("ts", int(time.time() * 1000))
                self.on_orderbook(std_sym, MarketType.PERPETUAL, bids, asks, ts)

        elif channel == "trade" and "data" in msg:
            trades = msg["data"]
            if isinstance(trades, list) and self.on_trade:
                for t in trades:
                    side = OrderSide.BUY if not t.get("m", False) else OrderSide.SELL
                    trade_event = TradeEvent(
                        symbol=std_sym,
                        market_type=MarketType.PERPETUAL,
                        price=float(t.get("p", 0)),
                        quantity=float(t.get("q", 0)),
                        side=side,
                        timestamp=int(t.get("T", time.time() * 1000)),
                        is_large_trade=float(t.get("q", 0)) * float(t.get("p", 0)) > 10000.0
                    )
                    self.on_trade(trade_event)

        elif channel == "kline_1m" and "data" in msg:
            if self.on_kline:
                self.on_kline(std_sym, MarketType.PERPETUAL, "1m", msg)

    async def _run_spot_stream(self):
        """Spot stream loop for Basis and Arbitrage monitoring"""
        backoff = 1.0
        while self.running:
            try:
                logger.info(f"Connecting to Spot WS: {self.spot_ws_url}")
                async with websockets.connect(self.spot_ws_url, ssl=self.ssl_context, ping_interval=None) as ws:
                    backoff = 1.0
                    logger.info("Spot WS connected. Subscribing to spot channels...")

                    for std_sym, info in self.symbol_map.items():
                        spot_sym = info.get("bingx_spot_symbol", std_sym)
                        await ws.send(json.dumps({
                            "id": f"sub_spot_{spot_sym}",
                            "reqType": "sub",
                            "dataType": f"{spot_sym}@depth20"
                        }))

                    while self.running:
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            text = gzip.decompress(raw).decode("utf-8")
                        else:
                            text = raw

                        if text == "Ping":
                            await ws.send("Pong")
                            continue

                        try:
                            msg = json.loads(text)
                            if "data" in msg and isinstance(msg["data"], dict):
                                d = msg["data"]
                                if "bids" in d or "asks" in d:
                                    # Spot depth message
                                    bids = d.get("bids", [])
                                    asks = d.get("asks", [])
                                    ts = msg.get("timestamp", int(time.time() * 1000))
                                    dtype = msg.get("dataType", "")
                                    if "@" in dtype:
                                        spot_sym = dtype.split("@")[0]
                                        std_sym = self.spot_to_standard.get(spot_sym, spot_sym)
                                        if self.on_orderbook:
                                            self.on_orderbook(std_sym, MarketType.SPOT, bids, asks, ts)
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                logger.warning(f"Spot WS disconnected ({e}), reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
