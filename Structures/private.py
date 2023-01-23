import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict
from Structures.common import *



@dataclass
class CoinBalance:
    ccy: str
    equity: float
    equity_usd: float

@dataclass
class Account:
    datetime: datetime
    total_usd: float
    in_coins_usd: float
    coins: Dict #= field(default_factory=lambda: {})

@dataclass
class Position:
    side: Side
    margin_ccy: str
    instrument_type: InstrumentType
    instrument_id: str
    pos_size: float
    pos_ccy: str
    notional_usd: float
    upl: float



@dataclass
class FillOrder:
    id: str
    ticker: str
    inst_type: InstrumentType
    posSide: Side
    action: Action
    size: float
    fill_price: float
    fill_time: datetime
    state: FillStatus
    leverage: float
    fee: float
    pnl: float
    create_time: datetime

