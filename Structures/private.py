import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List
from Structures.common import *



@dataclass
class CoinBalance:
    ccy: str
    equity: float
    equity_usd: float

    @property
    def ticker(self):
        return self.ccy + '-USDT'

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

