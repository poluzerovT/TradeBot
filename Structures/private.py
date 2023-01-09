import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List

from Structures.trade import Action, Side

class InstrumentType(Enum):
    SPOT = 'SPOT'
    MARGIN = 'MARGIN'
    SWAP = 'SWAP'

@dataclass
class CoinBalance:
    ccy: str
    equity: float

@dataclass
class Account:
    coins: List[CoinBalance]
    datetime: datetime
    total_usd: float

@dataclass
class Position:
    side: Side
    ccy: str
    instrument_type: InstrumentType
    size: float
    upl: float

@dataclass
class Positions:
    positions: List[Position]
    datetime: datetime

@dataclass
class FillOrder:
    ticker: str
    inst_type: InstrumentType
    posSide: Side
    action: Action
    size: float
    fill_price: float
    fill_time: datetime
    state: str ##
    leverage: float
    fee: float
    pnl: float
    create_time: datetime

