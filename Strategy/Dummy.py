import asyncio

from Tools.AlertManager import AlertManager
from Strategy.StrategyBase import StrategyBase
from Structures.public import *
from Structures.private import *
from Structures.trade import *

from collections import deque


class DummyStrategy(StrategyBase):
    def __init__(self, config):
        super().__init__(config, True)
        self.name = 'Dummy'
        self.timeframe_min = 60
        self.alert_manager = AlertManager(config)
        self.candle_history = None
        self.candle_history_length = 10
        self.current_candle_start = None


    async def trader(self):
        while True:
            await asyncio.sleep(10)
            order = Order(
                action=Action.BUY,
                size=0,
                ticker='ETH-USDT',
                trading_mode=TradingMode.CROSS,
                order_type=OrderType.MARKET,
            )
            await self.connection.place_order(order)


    def update_candle_history(self, candle):
        if self.candle_history is None or len(self.candle_history) == 0:
            raise RuntimeError(f'Empty candle history')

        if self.candle_history[-1].datetime == candle.datetime:
            self.candle_history[-1] = candle

        elif self.candle_history[-1].datetime != candle.datetime:
            self.candle_history.append(candle)
            if len(self.candle_history) > self.candle_history_length:
                self.candle_history.popleft()

    async def candle_handler(self, candle: Candle):
        self.update_candle_history(candle)
    #
    # async def account_handler(self, account):
    #     # self.alert_manager.send_message(account, title='account')
    #
    # def positions_handler(self, positions: Positions):
    #     self.alert_manager.send_message(positions, title='positions')
    #
    # def order_response_handler(self, order_response: OrderResponse):
    #     self.alert_manager.send_message(order_response, title='order response')
    #
    # def order_cancel_response_handler(self, order_cancel_response: OrderCancelResponse):
    #     self.alert_manager.send_message(order_cancel_response, title='order cancel response')
