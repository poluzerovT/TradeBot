import asyncio
from abc import ABC
from typing import Dict
import numpy as np
from Strategy.StrategyBase import StrategyBase
from Structures.public import *
from Structures.private import *
from Structures.trade import *
from collections import deque
import pandas as pd
from pandas import DataFrame
import cvxpy as cp

from Tools.logger import Logger

logger = Logger(__name__).logger


def markovitz_portfolio(r, sigma, theta, tickers=None):
    tickers = tickers or range(r.shape[0])

    if isinstance(r, pd.Series):
        r = r.values
    if isinstance(sigma, pd.Series):
        sigma = sigma.values
    w = cp.Variable(r.shape)

    ret = r.T @ w
    risk = cp.quad_form(w, sigma)

    constraints = [cp.sum(w) == 1, w >= 0]

    prob = cp.Problem(
        cp.Maximize(ret - theta * risk),
        constraints
    )
    prob.solve()
    params = {
        'risk': risk.value,
        'return': ret.value,
    }
    return pd.Series(np.round(w.value, 7), index=tickers), params


class MarkowitzStrategy(StrategyBase):
    def __init__(self, config, debug=True):
        super().__init__(config, __name__, debug)

        self.min_balance = 8
        self.trade_amount = 10
        self.theta = 10
        self.quote_ccy = 'USDT'

        self.tf = config['markowitz']['timeframe']
        self.ccys: List[str] = config['markowitz']['tickers']

        self.candle_history: Dict[str: deque[Candle]] = {}
        self.instruments_info = {}
        self.candle_history_length = 30
        self.positions: List[Position] = None
        self.account: Account = None

        self.active_orders = []

        self.add_sequent_task(self.set_candles_history)
        self.add_sequent_task(self.set_instrument_info)
        self.add_parallel_task(self.monitor)

    async def monitor(self):
        while self.account is None and self.positions is None:
            await asyncio.sleep(5)

        logger.warning(f'Monitor started')
        while True:
            if self.account:
                logger.info(f'{self.account}')
            if self.positions:
                logger.info(f'{self.positions}')
            if self.active_orders:
                logger.warning(f'Active orders: {self.active_orders}')
            await asyncio.sleep(60 * 15)

    async def set_candles_history(self):
        for ccy in self.ccys:
            self.candle_history[ccy] = deque(
                await self.connection.get_history_candles(ticker=f'{ccy}-{self.quote_ccy}', tf=self.tf,
                                                          num_bars=self.candle_history_length))

    async def set_instrument_info(self):
        for ccy in self.ccys:
            self.instruments_info[ccy] = await self.connection.get_instrument_info(
                inst_type=InstrumentType.SPOT,
                inst_id=ccy,
            )
        logger.warning(f'Min position: \n{self.instruments_info}')

    def close_prices_to_df(self):
        d = pd.DataFrame({ticker: [x.close for x in self.candle_history[ticker]] for ticker in self.ccys})
        if d.shape[0] != self.candle_history_length:
            return None
        return d

    async def wait_orders_fill(self):
        while len(self.active_orders):
            await asyncio.sleep(1)
            logger.warning(f'Waiting for filling orders: {self.active_orders}')

    async def rebuild_portfolio(self, portfolio, prices):
        portfolio_usd = portfolio * self.trade_amount
        orders = {
            Action.SELL: [],
            Action.BUY: []
        }
        for ccy in self.ccys:
            price = prices[ccy]
            min_size = self.instruments_info[ccy].min_size
            min_size_usd = min_size * price
            new_pos_usd = portfolio_usd[ccy]

            order = None
            if ccy in self.account.coins:
                coin = self.account.coins[ccy]
                diff = new_pos_usd - coin.equity_usd
                # print(
                #     f'coin: {coin},'
                #     f'new_pos_usd: {new_pos_usd}',
                #     f'min_size: {min_size}',
                #     f'min_size_usd: {min_size_usd}',
                #     sep='\n')
                if new_pos_usd < 0.01 < coin.equity:
                    order = Order(
                        action=Action.SELL,
                        size=coin.equity,
                        ticker=f'{ccy}-{self.quote_ccy}',
                        trading_mode=TradingMode.CASH,
                        order_type=OrderType.MARKET,
                        target_ccy=TargetCcy.BASE_CCY,
                    )
                elif abs(diff) > 0.1:
                    order = Order(
                        action=Action(diff),
                        size=abs(diff),
                        ticker=f'{ccy}-{self.quote_ccy}',
                        trading_mode=TradingMode.CASH,
                        order_type=OrderType.MARKET,
                        target_ccy=TargetCcy.QUOTE_CCY,
                    )
            else:
                if new_pos_usd > min_size_usd:
                    order = Order(
                        action=Action.BUY,
                        size=new_pos_usd,
                        ticker=f'{ccy}-{self.quote_ccy}',
                        trading_mode=TradingMode.CASH,
                        order_type=OrderType.MARKET,
                        target_ccy=TargetCcy.QUOTE_CCY,
                    )
            if order is not None:
                orders[order.action].append(order)

        for order in orders[Action.SELL]:
            order_response = await self.connection.place_order(order)
            if order_response.status == OrderStatus.OK:
                self.active_orders.append(order)
                logger.warning(f'placed SELL order: {order}')
            else:
                logger.error(f'Invalid SELL order: {order}')

        await self.wait_orders_fill()

        for order in orders[Action.BUY]:
            order_response = await self.connection.place_order(order)
            if order_response.status == OrderStatus.OK:
                self.active_orders.append(order)
                logger.warning(f'placed BUY order: {order}')
            else:
                logger.error(f'Invalid BUY order: {order}')

    async def trader(self):
        while True:
            df = self.close_prices_to_df()
            if df is not None:
                # self.trade_amount = int(self.account.total_usd - self.account.in_coins_usd)
                # logger.warning(f'Set trade ammount to {self.trade_amount}')
                df_ret = (df.diff() / df.shift())
                prices = df.iloc[-1]
                r = df_ret.iloc[-1]
                sigma = df_ret.cov()
                portfolio, stats = markovitz_portfolio(r, sigma, self.theta, tickers=self.ccys)

                logger.info(f'\nExpected return: \n{r}\nPortfolio: \n{portfolio}\nExpected stats: \n{stats}')
                await self.rebuild_portfolio(portfolio, prices)

            await asyncio.sleep(60 * 30)

    async def update_candle_history(self, candle):
        ccy = candle.inst_id.replace(f'-{self.quote_ccy}', '')
        if ccy not in self.ccys:
            return
        if self.candle_history.get(ccy) is None:
            raise RuntimeError(f'Empty candle history for ccy: {ccy}')

        if self.candle_history[ccy][-1].datetime == candle.datetime:
            self.candle_history[ccy][-1] = candle

        elif self.candle_history[ccy][-1].datetime != candle.datetime:
            self.candle_history[ccy].append(candle)
            if len(self.candle_history[ccy]) > self.candle_history_length:
                self.candle_history[ccy].popleft()

    # HANDLERS
    async def candle_handler(self, candle: Candle):
        await self.update_candle_history(candle)

    async def account_handler(self, account: Account):
        self.account = account
        if self.account.total_usd < self.min_balance:
            self.alert_manager.send_message(f'BALANCE < {self.min_balance}\n{self.account}')
            await self.exit()

    async def positions_handler(self, positions: List[Position]):
        self.positions = positions

    async def fill_order_handler(self, fill_order: FillOrder):
        logger.info(f'Gor fill order: {fill_order}')
        for order in self.active_orders:
            if order.id == fill_order.id:
                order.fill_status = fill_order.state
                if order.fill_status == FillStatus.FILLED:
                    self.active_orders.remove(order)
                    self.alert_manager.send_message(fill_order, title='filled order')
                    logger.info(f'Filled order: {order}')

