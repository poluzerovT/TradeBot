import asyncio

from abc import abstractmethod

from Tools.AlertManager import AlertManager
from Exchange.Okx import OkxConnection
from Structures.public import *
from Structures.private import *
from Structures.trade import *
from Tools.logger import Logger

logger = Logger(__name__).logger


class StrategyBase:
    def __init__(self, config, name):
        self.name = name
        self.queue = asyncio.Queue()
        self.connection = OkxConnection(config, self.queue)
        self.alert_manager = AlertManager(config)
        self.tasks = []
        self.pretasks = []

    async def listen_to_queue(self):
        while True:
            obj = await self.queue.get()
            # logger.info(f'Processing msg: {obj}')
            # public
            if isinstance(obj, Candle):
                self.candle_handler(obj)
            # private
            elif isinstance(obj, Positions):
                self.positions_handler(obj)
            elif isinstance(obj, Account):
                self.account_handler(obj)
            elif isinstance(obj, FillOrder):
                self.fill_order_handler(obj)
            # trade
            elif isinstance(obj, OrderResponse):
                self.order_response_handler(obj)
            # elif isinstance(obj, OrderCancelResponse):
            #     self.order_cancel_response_handler(obj)

    async def run(self):
        await self.connection.run()

        self.alert_manager.send_message(f'Run {self.name}')
        self.tasks.append(asyncio.create_task(self.listen_to_queue()))

        for pretask in self.pretasks:
            self.tasks.append(asyncio.create_task(pretask()))

        await asyncio.gather(*self.tasks)

    def add_pretask(self, pretask):
        self.pretasks.append(pretask)

    #  MOCKED
    def place_order(self, order: Order):
        # self.alert_manager.send_message(order)
        self.connection.place_order(order)

    @abstractmethod
    def candle_handler(self, obj):
        pass

    @abstractmethod
    def positions_handler(self, obj):
        pass

    @abstractmethod
    def order_response_handler(self, obj):
        pass

    @abstractmethod
    def order_cancel_response_handler(self, obj):
        pass

    @abstractmethod
    def account_handler(self, obj):
        pass

    @abstractmethod
    def fill_order_handler(self, obj):
        pass
