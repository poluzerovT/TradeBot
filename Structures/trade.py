import json
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class Side(Enum):
    LONG = 'LONG'
    SHORT = 'SHORT'

class Action(Enum):
    SELL = 'SELL'
    BUY = 'BUY'

class OrderType(Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'


class TradingMode(Enum):
    ISOLATED = 'ISOLATED'
    CROSS = 'CROSS'
    CASH = 'CASH'


@dataclass
class Order:
    action: Action
    size: float
    ticker: str
    trading_mode: TradingMode
    order_type: OrderType
    posSide: Side = None


@dataclass
class OrderCancel:
    inst_id: str
    order_id: str


# -----------------------------------   RECEIVABLE ------------------

class OrderStatus(Enum):
    OK = 'OK'
    ERROR = "ERROR"

@dataclass
class OrderResponse:
    order_id: str
    status: OrderStatus
    data: str
    op: str
