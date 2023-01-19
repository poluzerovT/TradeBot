from dataclasses import dataclass
from Structures.common import *


class TargetCcy(Enum):
    BASE_CCY = 'base_ccy'
    QUOTE_CCY = 'quote_ccy'

@dataclass
class Order:
    action: Action
    size: float
    ticker: str
    trading_mode: TradingMode
    order_type: OrderType
    posSide: Side = None
    target_ccy: TargetCcy = None


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
