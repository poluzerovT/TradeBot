import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


@dataclass
class Candle:
    inst_id: Optional[str] = None
    timestamp_ms: Optional[int] = None
    datetime: Optional[datetime] = None
    timeframe: Optional[str] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None