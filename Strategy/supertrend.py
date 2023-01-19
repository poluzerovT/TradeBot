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


class SupertrendStatus:
    def __init__(self, period, mul):
        self.trend = None
        self.trend_prev = self.trend
        self.up = np.nan
        self.low = np.nan
        self.low_prev = np.nan
        self.up_prev = np.nan
        self.mul = mul
        self.period = period

    def __repr__(self):
        res = {}
        for k, v in self.__dict__.items():
            if isinstance(v, float):
                v = np.round(v, 3)
            res[k] = v
        return repr(res)
        # return repr(self.__dict__)

    def trend_changed(self):
        return self.trend != self.trend_prev

    def calc(self, row, new_candle):
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
        if new_candle:
            self.up_prev = self.up
            self.low_prev = self.low

        self.up = float(up.iloc[-1])
        self.low = float(low.iloc[-1])

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
        else:
            if (self.trend is None or self.trend == Trend.UP) and self.low < self.low_prev:
                self.low = self.low_prev
            if (self.trend is None or self.trend == Trend.DOWN) and self.up > self.up_prev:
                self.up = self.up_prev

        if self.trend == Trend.UP:
            self.up = np.nan
        elif self.trend == Trend.DOWN:
            self.low = np.nan


class SupertrendStrategy(StrategyBase):
    def __init__(self, config):
        super().__init__(config, __name__)
        self.new_candle = False
        self.positions = None
        self.account = None
        self.trade_amount = config['supertrend']['trade_amount']
        self.trade_ticker = config['supertrend']['trade_ticker']
        self.trade_tf = config['supertrend']['timeframe']
        self.atr_period = config['supertrend']['atr_period']
        self.mult = config['supertrend']['mult']

        self.candle_history: deque[Candle] = deque()
        self.candle_history_length = self.atr_period
        self.current_candle_start = None
        self.add_parallel_task(self.trader)

    def candles_history_df(self):
        return pd.DataFrame(self.candle_history)

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
        while self.candle_history is None:
            await asyncio.sleep(5)
        self.supertrend_status = SupertrendStatus(self.atr_period, self.mult)

        logger.warning(f'Trader started')
        self.alert_manager.send_message(f'Trader started')

        while True:
            await asyncio.sleep(10)
            candles_df = self.candles_history_df()
            self.supertrend_status.calc(candles_df, self.new_candle)
            self.new_candle = False

            logger.info(self.supertrend_status)

            if self.supertrend_status.trend_changed():
                # logger.warning(f'Trend changed: {self.supertrend_status}')
                if self.supertrend_status.trend_prev == Trend.UP:
                    await self.connection.place_order(self._close_long_order())
                elif self.supertrend_status.trend_prev == Trend.DOWN:
                    await self.connection.place_order(self._close_short_order())

                if self.supertrend_status.trend == Trend.UP:
                    await self.connection.place_order(self._open_long_order())
                elif self.supertrend_status.trend == Trend.DOWN:
                    await self.connection.place_order(self._open_short_order())

    async def update_candle_history(self, candle):
        if self.current_candle_start is None:
            self.current_candle_start = candle.datetime
            self.candle_history = deque(
                await self.connection.get_history_candles(ticker=self.trade_ticker, tf=self.trade_tf,
                                                          num_bars=self.candle_history_length - 1))
            self.candle_history.append(candle)
        if self.current_candle_start == candle.datetime:
            self.candle_history[-1] = candle
        elif self.current_candle_start != candle.datetime:
            self.new_candle = True
            self.current_candle_start = candle.datetime
            self.candle_history.append(candle)
            if len(self.candle_history) > self.candle_history_length:
                self.candle_history.popleft()

    async def candle_handler(self, candle: Candle):
        await self.update_candle_history(candle)

    def account_handler(self, account: Account):
        self.account = account

    def positions_handler(self, positions: Positions):
        self.positions = positions

    def order_response_handler(self, order_response: OrderResponse):
        self.alert_manager.send_message(order_response, title='order response')
        logger.info(f'Gor order response: {order_response}')
        pass

    def fill_order_handler(self, fill_order: FillOrder):
        self.alert_manager.send_message(fill_order, title='fill order')
        logger.info(f'Gor fill order: {fill_order}')
