import asyncio
import time

from Strategy.StrategyBase import StrategyBase
from Structures.public import *
from Structures.private import *
from Structures.trade import *

from collections import deque

import pandas as pd
from pandas import DataFrame

from Tools.logger import Logger

logger = Logger(__name__).logger


def crossover(x, y):
    return (x > y) & (x.shift() < y.shift())


def tutci_online(data: DataFrame, entr_length=20, exit_length=10):
    high = data['high']
    low = data['low']
    close = data['close']

    up = high.rolling(window=entr_length).max()
    down = low.rolling(window=entr_length).min()

    sup = high.rolling(window=exit_length).max()
    sdown = low.rolling(window=exit_length).min()

    buy_signal = close >= up.shift()
    sell_signal = close <= down.shift()#(close == down.shift()) | crossover(down.shift(), close)
    buy_exit = close <= sdown.shift()#(close == sdown.shift()) | crossover(sdown.shift(), close)
    sell_exit = close >= sup.shift()#(close == sup.shift()) | crossover(close, sup.shift())

    # buy_signal = (high == up.shift()) | crossover(high, up.shift())
    # sell_signal = (low == down.shift()) | crossover(down.shift(), low)
    # buy_exit = (low == sdown.shift()) | crossover(sdown.shift(), low)
    # sell_exit = (high == sup.shift()) | crossover(high, sup.shift())
    return {
        'long_enter': bool(buy_signal.iloc[-1]),
        'short_enter': bool(sell_signal.iloc[-1]),
        'long_exit': bool(buy_exit.iloc[-1]),
        'short_exit': bool(sell_exit.iloc[-1])
    }


class TutciStatus:
    def __init__(self):
        self._in_position: bool = False
        self._side: Optional[Side] = None
        self._size: float = 0

    def __repr__(self):
        return repr(self.__dict__)

    def close(self):
        self._in_position = False

    def open(self, order: Order):
        self._in_position = True
        self._side = Side.LONG if order.action == Action.BUY else Side.SHORT
        self._size = order.size

    @property
    def side(self):
        if not self._in_position:
            self._side = None
        return self._side

    @property
    def size(self):
        if not self._in_position:
            self._size = 0
        return self._size

    @property
    def in_position(self):
        return self._in_position


class TutciStrategy(StrategyBase):
    def __init__(self, config):
        super().__init__(config, __name__)

        self.positions = None
        self.account = None
        self.tutci_status = None
        self.trade_amount = config['tutci']['trade_amount']
        self.trade_ticker = config['tutci']['trade_ticker']
        self.trade_tf = config['tutci']['timeframe']
        self.enter_length = config['tutci']['enter_length']
        self.exit_length = config['tutci']['exit_length']

        self.candle_history: deque[Candle] = deque()
        self.candle_history_length = self.enter_length + 1
        self.current_candle_start = None

        self.add_parallel_task(self.trader)
        # self.add_pretask(self.notifier)

    def candles_history_df(self):
        return pd.DataFrame(self.candle_history)

    async def notifier(self):
        while True:
            if self.account or self.positions:
                self.alert_manager.send_message(f'{self.positions}\n\n{self.account}')
            await asyncio.sleep(5 * 60)

    def _close_long_order(self):
        order = Order(
            action=Action.SELL,
            size=self.tutci_status.size,
            ticker=self.trade_ticker,
            trading_mode=TradingMode.ISOLATED,
            order_type=OrderType.MARKET,

        )
        return order

    def _close_short_order(self):
        order = Order(
            action=Action.BUY,
            size=self.tutci_status.size,
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

        self.tutci_status = TutciStatus()
        logger.warning(f'Trader started')
        self.alert_manager.send_message(f'Trader started')

        while True:
            await asyncio.sleep(5)
            candles_df = self.candles_history_df()

            signals = tutci_online(candles_df, self.enter_length, self.exit_length)

            if any(signals.values()):
                _ = {k: v for k, v in signals.items() if v}
                logger.info(f'Got signals: {_}')

            if self.tutci_status.side == Side.LONG and signals['long_exit']:
                order = self._close_long_order()
                await self.connection.place_order(order)
                self.tutci_status.close()

            elif self.tutci_status.side == Side.SHORT and signals['short_exit']:
                order = self._close_short_order()
                await self.connection.place_order(order)
                self.tutci_status.close()

            if not self.tutci_status.in_position:
                if signals['long_enter']:
                    order = self._open_long_order()
                    await self.connection.place_order(order)
                    self.tutci_status.open(order)
                elif signals['short_enter']:
                    order = self._open_short_order()
                    await self.connection.place_order(order)
                    self.tutci_status.open(order)

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
