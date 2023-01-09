import asyncio

from Tools.AlertManager import AlertManager
from Strategy.StrategyBase import StrategyBase
from Structures.public import *
from Structures.private import *
from Structures.trade import *

from collections import deque


class DummyStrategy(StrategyBase):
    def __init__(self, config):
        super().__init__(config)
        self.name = 'Dummy'
        self.timeframe_min = 60
        self.alert_manager = AlertManager(config)
        self.candle_history = deque()
        self.candle_history_length = 10
        self.current_candle_start = None

        # self.add_task(asyncio.create_task(self.trader()))
        self.in_position = False

    async def trader(self):
        await asyncio.sleep(90)
        if not self.in_position:
            order = Order(
                side=Action.BUY,
                size=1,
                inst_id='DOT-USDT-SWAP',
                trading_mode=TradingMode.ISOLATED,
                order_type=OrderType.MARKET)
            await self.connection.place_order(order)
            self.in_position = True
            self.alert_manager.send_message(f'Opening position {order}')
        await asyncio.sleep(30)
        if self.in_position:
            order = Order(
                side=Action.SELL,
                size=1,
                inst_id='DOT-USDT-SWAP',
                trading_mode=TradingMode.ISOLATED,
                order_type=OrderType.MARKET)
            await self.connection.place_order(order)
            self.alert_manager.send_message(f'Opening position {order}')

    def update_candle_history(self, candle):
        if self.current_candle_start is None:
            self.current_candle_start = candle.datetime
            self.candle_history.append(candle)
        if self.current_candle_start == candle.datetime:
            self.candle_history[-1] = candle
        elif self.current_candle_start != candle.datetime:
            self.candle_history.append(candle)
            if len(self.candle_history) > self.candle_history_length:
                self.candle_history.popleft()

    def candle_handler(self, candle: Candle):
        self.update_candle_history(candle)

    def account_handler(self, account):
        self.alert_manager.send_message(account, title='account')

    def positions_handler(self, positions: Positions):
        self.alert_manager.send_message(positions, title='positions')

    def order_response_handler(self, order_response: OrderResponse):
        self.alert_manager.send_message(order_response, title='order response')

    def order_cancel_response_handler(self, order_cancel_response: OrderCancelResponse):
        self.alert_manager.send_message(order_cancel_response, title='order cancel response')
