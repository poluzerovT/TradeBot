from dataclasses import dataclass
from enum import Enum
from typing import Any


class InstrumentType(Enum):
    SPOT = 'SPOT'
    MARGIN = 'MARGIN'
    SWAP = 'SWAP'

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if value in ['spot']:
            value = 'SPOT'
        elif value in ['margin']:
            value = 'MARGIN'
        elif value in ['swap']:
            value = 'SWAP'
        for member in cls:
            if member.value == value:
                return member
        return None

    def __repr__(self):
        return self.value

class Side(Enum):
    LONG = 'LONG'
    SHORT = 'SHORT'
    NET = 'NET'

    @classmethod
    def _missing_(cls, value):
        if value in ['long']:
            value = 'LONG'
        elif value in ['short']:
            value = 'SHORT'
        elif value in ['net']:
            value = 'NET'
        for member in cls:
            if member.value == value:
                return member
        return None

class Action(Enum):
    SELL = 'SELL'
    BUY = 'BUY'

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, float) and value > 0:
            value = 'BUY'
        elif isinstance(value, float) and value < 0:
            value = 'SELL'
        for member in cls:
            if member.value == value:
                return member
        return None

    def __str__(self):
        return self.value

    # def __repr__(self):
    #     return repr(self.value)


class OrderType(Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'

    def __str__(self):
        return self.value

    def __repr__(self):
        return repr(self.value)


class TradingMode(Enum):
    ISOLATED = 'ISOLATED'
    CROSS = 'CROSS'
    CASH = 'CASH'

    def __str__(self):
        return self.value

    def __repr__(self):
        return repr(self.value)

class FillStatus(Enum):
    PLACED = 'PLACED'
    FILLED = 'FILLED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    CANCELED = 'CANCELED'
    LIVE = 'LIVE'

    @classmethod
    def _missing_(cls, value):
        if value in ['filled']:
            value = 'FILLED'
        elif value in ['partially_filled']:
            value = 'PARTIALLY_FILLED'
        elif value in ['canceled']:
            value = 'CANCELED'
        elif value in ['live']:
            value = 'LIVE'

        for member in cls:
            if member.value == value:
                return member
        return None

    def __str__(self):
        return self.value

    def __repr__(self):
        return repr(self.value)
@dataclass
class InstrumentInfo:
    inst_type: InstrumentType
    inst_id: str
    contract_value: float
    min_size: float
    tick_size: float
