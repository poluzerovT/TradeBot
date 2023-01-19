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
    def __init__(self, config, name, debug=True):
        self.name = name
        self.queue = asyncio.Queue()
        self.connection = OkxConnection(config, self.queue, debug)
        self.alert_manager = AlertManager(config)
        self.tasks = []
        self.parallel_tasks = []
        self.sequent_tasks = []
        self.trader_task = None

    async def listen_to_queue(self):
        while True:
            obj = await self.queue.get()
            # public
            if isinstance(obj, Candle):
                await self.candle_handler(obj)
            # private
            elif isinstance(obj, Account):
                await self.account_handler(obj)
            elif isinstance(obj, FillOrder):
                await self.fill_order_handler(obj)
            # trade
            elif isinstance(obj, OrderResponse):
                await self.order_response_handler(obj)
            elif isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], Position):
                await self.positions_handler(obj)

    async def monitor_trader(self):
        while not self.trader_task.done():
            await asyncio.sleep(10)
        logger.error(f'Trader stopped.')

    async def run(self):
        await self.connection.run()
        for task in self.sequent_tasks:
            await task()
        for task in self.parallel_tasks:
            self.tasks.append(asyncio.create_task(task()))

        self.tasks.append(asyncio.create_task(self.listen_to_queue()))

        self.trader_task = asyncio.create_task(self.trader())
        self.tasks.append(asyncio.create_task(self.monitor_trader()))

        self.alert_manager.send_message(f'Trader {self.name} started')

        await asyncio.gather(*self.tasks, self.trader_task)

    def add_parallel_task(self, task):
        self.parallel_tasks.append(task)

    def add_sequent_task(self, task):
        self.sequent_tasks.append(task)

    @abstractmethod
    def trader(self):
        pass

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
