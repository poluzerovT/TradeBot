import asyncio
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


def markovitz_portfolio(r, sigma, theta, can_short, tickers=None):
    tickers = tickers or range(r.shape[0])
    print(r, type(r), r.shape)
    w = cp.Variable(r.shape)  # portfolio

    ret = r.T @ w
    risk = cp.quad_form(w, sigma)

    if can_short:
        constraints = [cp.norm(w, 1) <= 1]
    else:
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
    return pd.Series(np.round(w.value, 3), index=tickers), params


class MarkowitzStrategy(StrategyBase):
    def __init__(self, config, debug=True):
        super().__init__(config, __name__, debug)

        self.trade_amount = 1000
        self.theta = 100
        self.leverage = 5
        self.tf = config['markowitz']['timeframe']
        self.tickers: List[str] = config['markowitz']['tickers']
        self.candle_history: Dict[deque[Candle]] = {}
        self.instruments_info = {}
        self.candle_history_length = 3
        self.current_candle_start = None
        self.positions = None
        self.add_parallel_task(self.set_instrument_info)
        self.add_parallel_task(self.trader)

    async def set_instrument_info(self):
        for ticker in self.tickers:
            self.instruments_info[ticker] = await self.connection.get_instrument_info(
                inst_type=InstrumentType.SWAP,
                uly=ticker.replace('-SWAP', '')
            )

    def close_prices_df(self):
        d = pd.DataFrame({k: [x.close for x in v] for k, v in self.candle_history.items() if k in self.tickers})
        if d.shape[0] != self.candle_history_length:
            return None
        return d

    def close_all_positions(self):
        if self.positions is None:
            return
        for pos in self.positions:
            order = Order(
                action=Action.SELL if pos.side == Side.LONG else Action.BUY,
                size=pos.size,
                ticker=pos.ccys,
                trading_mode=TradingMode.ISOLATED,
                order_type=OrderType.MARKET,
            )
            self.connection.place_order(order)

    async def open_portfolio(self, portfolio, prices):
        for ticker, w in portfolio.items():
            if abs(w) > 0:
                size = int(abs(self.leverage * w * self.trade_amount / (prices[ticker] * self.instruments_info[ticker].contract_value)))
                order = Order(
                    action=Action.BUY if w > 0 else Action.SELL,
                    size=size,
                    ticker=ticker,
                    trading_mode=TradingMode.ISOLATED,
                    order_type=OrderType.MARKET,
                )
                self.alert_manager.send_message(order)
                await self.connection.place_order(order)

    async def trader(self):
        wait = True
        while wait:
            df = self.close_prices_df()
            print(df)
            if df is not None:
                wait = False
            await asyncio.sleep(5)
        while True:
            df = self.close_prices_df()
            if df is not None:
                # closing
                self.close_all_positions()

                df_ret = (df.diff() / df.shift())
                prices = df.iloc[-1]
                r = df_ret.mean(axis=0).values
                sigma = df_ret.cov().values
                portfolio, _ = markovitz_portfolio(r, sigma, self.theta, True, tickers=self.tickers)
                portfolio = pd.Series(np.ones(len(self.tickers)) / len(self.tickers), index=self.tickers)
                print(portfolio.abs().sum())
                await self.open_portfolio(portfolio, prices)

                # opening

            await asyncio.sleep(60 * 30)  # 30 min

    async def update_candle_history(self, candle):
        ticker = candle.inst_id
        if self.candle_history.get(ticker) is None:
            self.candle_history[ticker] = deque(
                await self.connection.get_history_candles(ticker=ticker, tf=self.tf,
                                                          num_bars=self.candle_history_length - 1))
            self.candle_history[ticker].append(candle)

        if self.candle_history[ticker][-1].datetime == candle.datetime:
            self.candle_history[ticker][-1] = candle

        elif self.candle_history[ticker][-1].datetime != candle.datetime:
            self.candle_history[ticker].append(candle)
            if len(self.candle_history[ticker]) > self.candle_history_length:
                self.candle_history[ticker].popleft()

    async def candle_handler(self, candle: Candle):
        await self.update_candle_history(candle)

    def account_handler(self, account: Account):
        self.account = account

    def positions_handler(self, positions: List[Position]):
        self.positions = positions

    def order_response_handler(self, order_response: OrderResponse):
        self.alert_manager.send_message(order_response, title='order response')
        logger.info(f'Gor order response: {order_response}')
        pass

    def fill_order_handler(self, fill_order: FillOrder):
        self.alert_manager.send_message(fill_order, title='fill order')
        logger.info(f'Gor fill order: {fill_order}')
