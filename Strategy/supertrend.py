import asyncio
import numpy as np
from Strategy.StrategyBase import StrategyBase
from Structures.public import *
from Structures.private import *
from Structures.trade import *
from collections import deque
import pandas as pd
from pandas import DataFrame

from Tools.logger import Logger

logger = Logger(__name__).logger


class Trend(Enum):
    UP = 'UP'
    DOWN = 'DOWN'

    def __repr__(self):
        return repr(self.value)


class EmaTrend:
    def __init__(self, leng):
        self.leng = leng
        self.trend = None

    def calculate(self, df: pd.DataFrame):
        close = df['close']
        ema = close.rolling(self.leng).mean()
        ema_diff = ema.diff()
        self.trend = Trend.UP if ema_diff.iloc[-1] > 0 else Trend.DOWN

    def __repr__(self):
        return repr(self.trend)


class SupertrendStatus:
    def __init__(self, period, mul):
        self.price_now = np.nan
        self.trend = None
        self.trend_prev = None
        self.up = np.nan
        self.up_prev = np.nan
        self.low = np.nan
        self.low_prev = np.nan

        self.mul = mul
        self.period = period

    def __repr__(self):
        res = {}
        for k, v in self.__dict__.items():
            if isinstance(v, float):
                v = np.round(v, 3)
            res[k] = v
        return repr(res)

    def trend_changed(self):
        return self.trend != self.trend_prev

    def calc(self, row):
        if row.shape[0] < self.period:
            return
        high = row['high']
        low = row['low']
        close = row['close']
        price_now = float(close.iloc[-1])

        price_diffs = [high - low,
                       high - close.shift(),
                       close.shift() - low]
        true_range = pd.concat(price_diffs, axis=1)
        true_range = true_range.abs().max(axis=1)

        # atr = true_range.ewm(alpha=1/atr_period,min_periods=atr_period).mean()
        atr = true_range.rolling(self.period).mean()
        hl2 = (high + low) / 2

        up = hl2 + (self.mul * atr)
        low = hl2 - (self.mul * atr)

        self.trend_prev = self.trend
        self.up = float(up.iloc[-1])
        self.low = float(low.iloc[-1])
        self.price_now = price_now
        if price_now > self.up_prev:
            if self.trend == Trend.DOWN:
                self.trend = None
            else:
                self.trend = Trend.UP

        elif price_now < self.low_prev:
            if self.trend == Trend.UP:
                self.trend = None
            else:
                self.trend = Trend.DOWN

        # if self.trend is None:
        self.up_prev = min(self.up_prev, self.up) if not np.isnan(self.up_prev) else self.up
        self.low_prev = max(self.low_prev, self.low) if not np.isnan(self.low_prev) else self.low

        if self.trend == Trend.UP:
            self.up_prev = np.nan
            # self.low_prev = max(self.low_prev, self.low) if not np.isnan(self.low_prev) else self.low

        elif self.trend == Trend.DOWN:
            # self.up_prev = min(self.up_prev, self.up) if not np.isnan(self.up_prev) else self.up
            self.low_prev = np.nan

    def to_dict(self):
        res = {}
        for k, v in self.__dict__.items():
            if isinstance(v, float):
                v = np.round(v, 3)
            res[k] = v
        return res


class SupertrendStrategy(StrategyBase):
    def __init__(self, config, debug=True):
        super().__init__(config, __name__, debug)
        self.positions = None
        self.account = None
        self.active_position = None
        self.trade_amount = config['supertrend']['trade_amount']
        self.trade_ticker = config['supertrend']['trade_ticker']
        self.trade_tf = config['supertrend']['timeframe']

        self.atr_period = config['supertrend']['atr_period']
        self.mult = config['supertrend']['mult']
        self.ema_leng = config['supertrend']['ema_leng']

        self.candle_history: deque[Candle] = deque()
        self.candle_history_length = max(self.atr_period, self.ema_leng) + 2
        self.current_candle_start = None
        self.add_sequent_task(self.set_candles_history)

    def candles_history_df(self):
        return pd.DataFrame(self.candle_history)

    async def set_candles_history(self):
        self.candle_history = deque(
            await self.connection.get_history_candles(
                ticker=self.trade_ticker,
                tf=self.trade_tf,
                num_bars=self.candle_history_length)
        )

    def _close_long_order(self):
        order = Order(
            action=Action.SELL,
            size=self.trade_amount,
            ticker=self.trade_ticker,
            trading_mode=TradingMode.ISOLATED,
            order_type=OrderType.MARKET,
        )
        return order

    def _close_short_order(self):
        order = Order(
            action=Action.BUY,
            size=self.trade_amount,
            ticker=self.trade_ticker,
            trading_mode=TradingMode.ISOLATED,
            order_type=OrderType.MARKET,
        )
        return order

    def _open_long_order(self):
        order = Order(
            action=Action.BUY,
            size=self.trade_amount,
            ticker=self.trade_ticker,
            trading_mode=TradingMode.ISOLATED,
            order_type=OrderType.MARKET,
        )
        return order

    def _open_short_order(self):
        order = Order(
            action=Action.SELL,
            size=self.trade_amount,
            ticker=self.trade_ticker,
            trading_mode=TradingMode.ISOLATED,
            order_type=OrderType.MARKET,
        )
        return order

    async def trader(self):
        self.ema_trend = EmaTrend(self.ema_leng)
        self.supertrend_status = SupertrendStatus(self.atr_period, self.mult)
        if self.active_position is not None:
            self.supertrend_status.trend = Trend.UP if self.active_position.side == Side.LONG else Trend.DOWN
        logger.warning(f'Trader started')

        while True:
            await asyncio.sleep(15)
            candles_df = self.candles_history_df()
            self.supertrend_status.calc(candles_df)
            self.ema_trend.calculate(candles_df)

            logger.info(f'{self.supertrend_status}, {self.ema_trend}')

            if self.supertrend_status.trend_changed():
                logger.warning(f'Trend changed. Global: {self.ema_trend}. Supertrend:{self.supertrend_status.trend}')
                # close position
                if self.active_position is not None:
                    if self.active_position.side == Side.LONG and self.supertrend_status.trend != Trend.UP:
                        order = self._close_long_order()
                        resp = await self.connection.place_order(order)
                        if resp.status != OrderStatus.OK:
                            logger.error(f'Cant close long position: {order}, {resp}')

                    elif self.active_position.side == Side.SHORT and self.supertrend_status.trend != Trend.DOWN:
                        order = self._close_short_order()
                        resp = await self.connection.place_order(order)
                        if resp.status != OrderStatus.OK:
                            logger.error(f'Cant close short position: {order}, {resp}')

                # open if both trends in same direction
                if self.supertrend_status.trend == Trend.UP:# and self.ema_trend.trend == Trend.UP:
                    order = self._open_long_order()
                    resp = await self.connection.place_order(order)
                    if resp.status != OrderStatus.OK:
                        logger.error(f'Cant open long position: {order}, {resp}')
                elif self.supertrend_status.trend == Trend.DOWN:# and self.ema_trend.trend == Trend.DOWN:
                    order = self._open_short_order()
                    resp = await self.connection.place_order(order)
                    if resp.status != OrderStatus.OK:
                        logger.error(f'Cant open short position: {order}, {resp}')

    async def update_candle_history(self, candle):
        if self.candle_history is None:
            raise RuntimeError(f'Empty candle history')

        if self.candle_history[-1].datetime == candle.datetime:
            self.candle_history[-1] = candle

        elif self.candle_history[-1].datetime != candle.datetime:
            self.candle_history.append(candle)
            if len(self.candle_history) > self.candle_history_length:
                self.candle_history.popleft()

    async def candle_handler(self, candle: Candle):
        if candle.inst_id == self.trade_ticker:
            await self.update_candle_history(candle)

    async def account_handler(self, account: Account):
        self.account = account

    async def positions_handler(self, positions: List[Position]):
        for position in positions:
            if position.instrument_id == self.trade_ticker:
                self.active_position = position

    async def order_response_handler(self, order_response: OrderResponse):
        self.alert_manager.send_message(order_response, title='order response')
        logger.info(f'Gor order response: {order_response}')
        pass

    async def fill_order_handler(self, fill_order: FillOrder):
        self.alert_manager.send_message(fill_order, title='fill order')
        logger.info(f'Gor fill order: {fill_order}')
