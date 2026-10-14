"""
Unified Data Schemas for Multi-Agent Quant Trading Bot
P0/P1 Specification - All timestamps are UTC milliseconds.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import time


class MarketType(str, Enum):
    SPOT = "spot"
    PERPETUAL = "perpetual"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class MarketRegime(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    SHOCK = "SHOCK"
    ABNORMAL = "ABNORMAL"


class StrategyType(str, Enum):
    MOMENTUM_LONG = "MOMENTUM_LONG"
    MOMENTUM_SHORT = "MOMENTUM_SHORT"
    SPOT_PERP_ARBITRAGE = "SPOT_PERP_ARBITRAGE"
    NO_TRADE = "NO_TRADE"


class OrderBookDepth(BaseModel):
    symbol: str
    market_type: MarketType
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    bids: List[List[float]] = Field(default_factory=list)  # [[price, qty], ...]
    asks: List[List[float]] = Field(default_factory=list)  # [[price, qty], ...]
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0
    obi: float = 0.0  # Order book imbalance (-1.0 to 1.0)
    microprice: float = 0.0
    is_stale: bool = False


class TradeEvent(BaseModel):
    symbol: str
    market_type: MarketType
    price: float
    quantity: float
    side: OrderSide
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    is_large_trade: bool = False


class Candle(BaseModel):
    symbol: str
    market_type: MarketType
    interval: str  # "1m", "5m", "15m", "20m"
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    close_time: int
    is_closed: bool = True


class FeatureSnapshot(BaseModel):
    symbol: str
    timestamp: int
    mid_price: float
    # Technical features
    return_1m: float = 0.0
    return_5m: float = 0.0
    return_15m: float = 0.0
    return_20m: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_slope: float = 0.0
    atr_14: float = 0.0
    realized_vol: float = 0.0
    volume_zscore: float = 0.0
    # Orderbook features
    spread_bps: float = 0.0
    obi_5: float = 0.0
    obi_10: float = 0.0
    microprice_deviation_bps: float = 0.0
    depth_bid_usd: float = 0.0
    depth_ask_usd: float = 0.0
    # Basis features
    perp_price: float = 0.0
    spot_price: float = 0.0
    basis_bps: float = 0.0
    funding_rate: float = 0.0
    is_valid: bool = True


class AgentOutput(BaseModel):
    agent_id: str
    symbol: str
    score: float = Field(..., ge=-1.0, le=1.0)  # -1.0 (strong short) to +1.0 (strong long)
    confidence: float = Field(..., ge=0.0, le=1.0)  # 0.0 to 1.0
    risk: float = Field(0.0, ge=0.0, le=1.0)  # 0.0 (low risk) to 1.0 (extreme risk)
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    ttl_ms: int = 1200000  # Default 20 mins TTL
    reason_codes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OpportunityEvaluation(BaseModel):
    symbol: str
    strategy: StrategyType
    opportunity_score: float
    expected_edge_bps: float
    confidence: float
    risk_score: float
    fee_bps: float
    slippage_bps: float
    net_edge_bps: float
    rank: int = 0
    passed_validation: bool = False
    rejection_reason: Optional[str] = None


class RiskDecision(BaseModel):
    decision_id: str
    symbol: str
    approved: bool
    position_size: float = 0.0  # In base asset quantity
    notional_usd: float = 0.0
    allocated_margin: float = 0.0
    leverage: int = 1
    soft_stop_roi: float = -0.05
    hard_stop_roi: float = -0.10
    soft_tp_roi: float = 0.15
    hard_tp_roi: float = 0.30
    reason: str = ""
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class PositionState(BaseModel):
    symbol: str
    market_type: MarketType
    side: PositionSide
    entry_price: float
    current_price: float
    quantity: float
    margin: float
    leverage: int
    unrealized_pnl: float
    net_roi: float  # Leveraged Net Position ROI (after fees)
    underlying_return: float  # Raw asset price % change
    peak_roi: float  # High water mark for Trailing Stop
    trailing_stop_active: bool = False
    soft_stop_roi: float = -0.05
    hard_stop_roi: float = -0.10
    soft_tp_roi: float = 0.15
    hard_tp_roi: float = 0.30
    entry_time: int
    last_update_time: int
    trace_id: str
