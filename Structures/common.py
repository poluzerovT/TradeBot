from dataclasses import dataclass
from enum import Enum

class InstrumentType(Enum):
    SPOT = 'SPOT'
    MARGIN = 'MARGIN'
    SWAP = 'SWAP'

    def __repr__(self):
        return self.value

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
class InstrumentInfo:
    inst_type: InstrumentType
    inst_id: str
    contract_value: float
    min_size: float
