from dataclasses import dataclass, field
import random

from Structures.common import *
from Structures.private import FillOrder


def id_generator():
    return str(int(random.random() * 1000000) % 1000000)


class TargetCcy(Enum):
    BASE_CCY = 'base_ccy'
    QUOTE_CCY = 'quote_ccy'


@dataclass
class OrderCancel:
    inst_id: str
    order_id: str


# -----------------------------------   RECEIVABLE ------------------

class OrderStatus(Enum):
    OK = 'OK'
    ERROR = "ERROR"

    def __str__(self):
        return self.value

    def __repr__(self):
        return repr(self.value)

@dataclass
class OrderResponse:
    status: OrderStatus
    order_id: str = ''
    op: str = ''

@dataclass
class Order:
    action: Action
    size: float
    ticker: str
    trading_mode: TradingMode
    order_type: OrderType
    id: str = field(default_factory=id_generator)
    fill_status: FillStatus = FillStatus.PLACED
    posSide: Side = None
    target_ccy: TargetCcy = None
    margin_ccy: str = None
