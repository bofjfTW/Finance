"""
Abstract Broker Interface
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional
from data.schema import PositionState, OrderSide, MarketType


class BaseBroker(ABC):
    @abstractmethod
    def get_equity(self) -> float:
        pass

    @abstractmethod
    def get_available_balance(self) -> float:
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, PositionState]:
        pass

    @abstractmethod
    def open_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        leverage: int,
        market_type: MarketType = MarketType.PERPETUAL,
        trace_id: str = ""
    ) -> Optional[PositionState]:
        pass

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        price: float,
        reason: str = "MANUAL"
    ) -> Optional[float]:
        """Closes position and returns realized PnL"""
        pass
