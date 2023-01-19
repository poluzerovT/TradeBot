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


def markovitz_portfolio(r, sigma, theta, lowerbands, tickers=None):
    tickers = tickers or range(r.shape[0])

    if isinstance(r, pd.Series):
        r = r.values
    if isinstance(sigma, pd.Series):
        sigma = sigma.values
    if isinstance(lowerbands, pd.Series):
        lowerbands = lowerbands.values

    w = cp.Variable(r.shape)

    ret = r.T @ w
    risk = cp.quad_form(w, sigma)

    constraints = [cp.sum(w) == 1, w >= lowerbands]

    prob = cp.Problem(
        cp.Maximize(ret - theta * risk),
        constraints
    )
    prob.solve()
    params = {
        'risk': risk.value,
        'return': ret.value,
    }
    return pd.Series(np.round(w.value, 3), index=tickers), params


class MarkowitzStrategy(StrategyBase):
    def __init__(self, config, debug=True):
        super().__init__(config, __name__, debug)

        self.trade_amount = 10
        self.theta = 1
        self.quote_ccy = 'USDT'

        self.tf = config['markowitz']['timeframe']
        self.tickers: List[str] = config['markowitz']['tickers']

        self.candle_history: Dict[str: deque[Candle]] = {}
        self.instruments_info = {}
        self.candle_history_length = 30
        self.positions = None
        self.account = None

        self.add_sequent_task(self.set_candles_history)
        self.add_sequent_task(self.set_instrument_info)
        self.add_parallel_task(self.monitor)

    async def monitor(self):
        while True:
            if self.account:
                logger.info(f'{self.account}')
            if self.positions:
                logger.info(f'{self.positions}')
            await asyncio.sleep(60)

    async def set_candles_history(self):
        for ticker in self.tickers:
            self.candle_history[ticker] = deque(
                await self.connection.get_history_candles(ticker=ticker, tf=self.tf,
                                                          num_bars=self.candle_history_length))

    async def set_instrument_info(self):
        for ticker in self.tickers:
            self.instruments_info[ticker] = await self.connection.get_instrument_info(
                inst_type=InstrumentType.SPOT,
                inst_id=ticker,
            )

    def close_prices_to_df(self):
        d = pd.DataFrame({ticker: [x.close for x in self.candle_history[ticker]] for ticker in self.tickers})
        if d.shape[0] != self.candle_history_length:
            return None
        return d

    async def close_portfolio(self):
        if self.account is None:
            return
        for coin in self.account.coins:
            if coin.ticker in self.tickers:
                logger.info(f'Closing position: \n{coin}')
                order = Order(
                    action=Action.SELL,
                    size=coin.equity,
                    ticker=coin.ticker,
                    trading_mode=TradingMode.CASH,
                    order_type=OrderType.MARKET,
                    target_ccy=TargetCcy.BASE_CCY,
                )
                await self.connection.place_order(order)

    async def open_portfolio(self, portfolio, prices):
        total_usd = 0
        for ticker, w in portfolio.items():
            if abs(w) > 0:
                size = abs(w * self.trade_amount / prices[ticker])
                total_usd += size * prices[ticker]
                order = Order(
                    action=Action.BUY,
                    size=size,
                    ticker=ticker,
                    trading_mode=TradingMode.CASH,
                    order_type=OrderType.MARKET,
                    target_ccy=TargetCcy.BASE_CCY,
                )
                self.alert_manager.send_message(f'{order}')
                await self.connection.place_order(order)
        logger.info(f'Placed portfolio. Total usd: {total_usd}')

    async def trader(self):
        lowerbands = pd.Series([x.min_size for x in self.instruments_info.values()], index=self.tickers)
        logger.error(f'lowerbounds: \n{lowerbands}')
        for i in range(1):
            # while True:
            df = self.close_prices_to_df()
            if df is not None:
                df_ret = (df.diff() / df.shift())
                prices = df.iloc[-1]
                r = df_ret.iloc[-1]
                sigma = df_ret.cov()
                portfolio, stats = markovitz_portfolio(r, sigma, self.theta, lowerbands, tickers=self.tickers)

                logger.info(f'\nExpected return: \n{r}\nPortfolio: \n{portfolio}\nExpected stats: \n{stats}')

                await self.close_portfolio()
                await self.open_portfolio(portfolio, prices)

            await asyncio.sleep(60 * 15)

        await self.close_portfolio()

    async def update_candle_history(self, candle):
        ticker = candle.inst_id
        if self.candle_history.get(ticker) is None:
            raise RuntimeError(f'Empty candle history for ticker: {ticker}')

        if self.candle_history[ticker][-1].datetime == candle.datetime:
            self.candle_history[ticker][-1] = candle

        elif self.candle_history[ticker][-1].datetime != candle.datetime:
            self.candle_history[ticker].append(candle)
            if len(self.candle_history[ticker]) > self.candle_history_length:
                self.candle_history[ticker].popleft()

    # HANDLERS
    async def candle_handler(self, candle: Candle):
        await self.update_candle_history(candle)

    async def account_handler(self, account: Account):
        self.account = account

    async def positions_handler(self, positions: List[Position]):
        self.positions = positions

    async def order_response_handler(self, order_response: OrderResponse):
        self.alert_manager.send_message(order_response, title='order response')
        logger.info(f'Gor order response: {order_response}')
        pass

    async def fill_order_handler(self, fill_order: FillOrder):
        self.alert_manager.send_message(fill_order, title='fill order')
        logger.info(f'Gor fill order: {fill_order}')
