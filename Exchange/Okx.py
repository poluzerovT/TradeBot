import asyncio
import base64
import hashlib
import hmac
import json
import random
import time
from typing import Dict, Any
from urllib.parse import urlencode

import aiohttp as aiohttp
import websockets

from Structures.private import *
from Structures.public import *
from Structures.trade import *
from Tools.logger import Logger

logger = Logger(__name__).logger


class Method(Enum):
    GET = 'GET'
    POST = 'POST'
    SET = 'SET'




async def handle_rest_response(result: aiohttp.ClientResponse) -> Dict:
    if result.status != 200:
        error_msg = await result.text()
        raise RuntimeError(
            f'Executing method {result.url}" resulted in error: {result.status} {error_msg}'
        )
    return await result.json()


class OkxConnection:
    def __init__(self, config, queue, debug=True):
        self.debug = debug

        self.reconnect_interval = 3600
        self.config = config
        self.queue = queue

        self.public_ws_url = self.config['okx_connection']['public_ws_url']
        self.private_ws_url = self.config['okx_connection']['private_ws_url']
        self.trade_ws_url = self.config['okx_connection']['trade_ws_url']
        self.rest_url = self.config['okx_connection']['rest_url']
        self._api_key = self.config['api_key']
        self._secret_key = self.config['secret_key']
        self._passphrase = self.config['passphrase']
        self.channels_public = self.config['channels_public']
        self.channels_private = self.config['channels_private']

        self.public_ws: websockets.WebSocketServerProtocol = None
        self.private_ws: websockets.WebSocketServerProtocol = None
        self.trade_ws: websockets.WebSocketServerProtocol = None
        self.rest_session: aiohttp.ClientSession = None

        self.listening_tasks = []
        self.reconnect_task = None

    # def __del__(self):
    #     for task in self.listening_tasks:
    #         if task:
    #             task.cancel()
    #     for ws in [self.public_ws, self.private_ws, self.trade_ws]:
    #         if ws:
    #             ws.close()
    #
    #     if self.reconnect_task:
    #         self.reconnect_task.cancel()
    #
    #
    #     print('destructed')

    # WEBSOCKET LISTENERS

    # WS LISTENERS
    async def _listen_to_public_ws(self):
        while True:
            message = await self.public_ws.recv()
            msg_json = json.loads(message)
            obj = self._object_from_json_public(msg_json)
            self.queue.put_nowait(obj)

    async def _listen_to_private_ws(self):
        while True:
            message = await self.private_ws.recv()
            msg_json = json.loads(message)
            obj = self._object_from_json_private(msg_json)
            self.queue.put_nowait(obj)

    # async def _listen_to_trade_ws(self):
    #     while True:
    #         message = await self.trade_ws.recv()
    #         if message == 'pong':
    #             continue
    #         msg_json = json.loads(message)
    #         obj = self._object_from_json_trade(msg_json)
    #         self.queue.put_nowait(obj)

    # JSON TO STRUCTURES CONVERTERS
    def _candle_from_json(self, msg: Dict, **params) -> Any:
        candles = []
        inst_id = params.get('instId') or msg.get('arg').get('instId')
        timeframe = params.get('timeframe') or msg.get('arg').get('channel').replace('candle', '')
        # if msg.get('arg'):
        #     inst_id = msg.get('arg').get('instId')
        #     timeframe = msg.get('arg').get('channel').replace('candle', '')
        # else:
        #     inst_id = params['instId']
        #     timeframe = params['timeframe']

        for data in msg.get('data'):
            candle = Candle(
                inst_id=inst_id,
                timeframe=timeframe,
                datetime=datetime.fromtimestamp(int(data[0]) // 1000),
                timestamp_ms=int(data[0]),
                open=float(data[1]),
                high=float(data[2]),
                low=float(data[3]),
                close=float(data[4]),
                volume=float(data[5]),
            )
            candles.append(candle)

        if len(candles) > 1:
            return candles
        return candles[0]

    def _positions_from_json(self, msg: Dict) -> List[Position]:
        # print(f'Position: \n{msg}')
        positions = []
        for data in msg['data']:
            pos = Position(
                side=Side(data['posSide']),
                margin_ccy=data['ccy'],
                instrument_type=InstrumentType(data['instType']),
                instrument_id=data['instId'],
                pos_size=float(data['pos']),
                pos_ccy=data['posCcy'],
                notional_usd=float(data['notionalUsd']) if data['notionalUsd'] else None,
                upl=float(data['upl']) if data['upl'] else None
            )
            positions.append(pos)
        return positions

    def _account_from_json(self, msg: Dict) -> Account:
        coins = {}
        timestamp_ms = int(msg['data'][0]['uTime'])
        dt = datetime.fromtimestamp(timestamp_ms // 1000)
        total_usd = 0
        for data in msg['data'][0]['details']:
            coin = CoinBalance(
                ccy=data['ccy'],
                equity=float(data['eq']),
                equity_usd=float(data['eqUsd'])
            )
            total_usd += float(data['eqUsd'])
            coins[coin.ccy] = coin

        usdt = coins.get('USDT').equity if 'USDT' in coins.keys() else 0
        return Account(coins=coins, datetime=dt, total_usd=total_usd, in_coins_usd=total_usd - usdt)

    def _order_response_from_json(self, msg: Dict) -> OrderResponse:
        return OrderResponse(
            op=msg['op'],
            order_id=msg['id'],
            status=OrderStatus.OK if msg['code'] == '0' else OrderStatus.ERROR,
            # data=msg['data']
        )

    def _multiple_order_response_from_json(self, msg: Dict) -> List[OrderResponse]:
        order_responses = []
        op = msg['op']
        id = msg['id']
        for d in msg['data']:
            order_response = OrderResponse(
                op=op,
                order_id=id,
                status=OrderStatus.OK if msg['code'] == '0' else OrderStatus.ERROR,
                # data=msg['data']
            )
            order_responses.append(order_response)
        return order_responses

    def _fill_order_from_json(self, msg: Dict) -> FillOrder:
        data = msg['data'][0]
        fill_order = FillOrder(
            id=data['clOrdId'],
            ticker=data['instId'],
            inst_type=InstrumentType(data['instType']),
            posSide=Side.LONG if data['posSide'] == 'long' else Side.SHORT if data['posSide'] == 'short' else None,
            action=Action.BUY if data['side'] == 'buy' else Action.SELL,
            size=float(data['sz']),
            fill_price=float(data['fillPx']) if data['fillPx'] else None,
            fill_time=datetime.fromtimestamp(int(data['fillTime']) // 1000) if data['fillTime'] else None,
            state=FillStatus(data['state']),
            leverage=float(data['lever']) if data['lever'] else None,
            fee=float(data['fee']) if data['fee'] else None,
            pnl=float(data['pnl']) if data['pnl'] else None,
            create_time=datetime.fromtimestamp(int(data['cTime']) // 1000)
        )

        return fill_order

    def _instrument_info_from_json(self, msg: Dict) -> InstrumentInfo:
        data = msg['data'][0]
        instrument_info = InstrumentInfo(
            inst_type=InstrumentType(data['instType']),
            inst_id=data['instId'],
            contract_value=float(data['ctVal']) if data['ctVal'] else None,
            min_size=float(data['minSz']),
            tick_size=float(data['tickSz']) if data['tickSz'] else None
        )
        return instrument_info

    # OBJECT TO JSON CONVERTERS
    def _order_to_json(self, order: Order) -> json:  # TODO: long/short or buy/sell account setting
        pos_side_map = {Side.LONG: 'long', Side.SHORT: 'short'}
        action_map = {Action.BUY: 'buy', Action.SELL: 'sell'}
        tdMode_map = {TradingMode.CROSS: 'cross', TradingMode.ISOLATED: 'isolated', TradingMode.CASH: 'cash'}
        ordType_map = {OrderType.MARKET: 'market', OrderType.LIMIT: 'limit'}
        tgtCcy_map = {TargetCcy.BASE_CCY: 'base_ccy', TargetCcy.QUOTE_CCY: 'quote_ccy'}

        msg = {
            "id": order.id,
            "op": "order",
            "args": [
                {
                    "side": action_map[order.action],
                    "sz": order.size,
                    "instId": order.ticker,
                    "tdMode": tdMode_map[order.trading_mode],
                    "ordType": ordType_map[order.order_type],
                    "clOrdId": order.id,

                    "tgtCcy": tgtCcy_map[order.target_ccy] if order.target_ccy else None,
                    'ccy': order.margin_ccy,
                }
            ]
        }
        for k, v in msg.items():
            if v is None:
                msg.pop(k)

        return json.dumps(msg, separators=(",", ":"))

    def _multiple_orders_to_json(self, orders: List[Order]):
        pos_side_map = {Side.LONG: 'long', Side.SHORT: 'short'}
        action_map = {Action.BUY: 'buy', Action.SELL: 'sell'}
        tdMode_map = {TradingMode.CROSS: 'cross', TradingMode.ISOLATED: 'isolated', TradingMode.CASH: 'cash'}
        ordType_map = {OrderType.MARKET: 'market', OrderType.LIMIT: 'limit'}
        tgtCcy_map = {TargetCcy.BASE_CCY: 'base_ccy', TargetCcy.QUOTE_CCY: 'quote_ccy'}
        args = []
        for order in orders:
            arg = {
                "side": action_map[order.action],
                "instId": order.ticker,
                "tdMode": tdMode_map[order.trading_mode],
                "ordType": ordType_map[order.order_type],
                "sz": order.size,
                "tgtCcy": tgtCcy_map[order.target_ccy],
            }
            args.append(arg)
        msg = {
            "id": id_generator(),
            "op": "batch-orders",
            "args": args
        }
        return json.dumps(msg, separators=(",", ":"))

    def _order_cancel_to_json(self, order_cancel: OrderCancel):
        msg = {
            "id": id_generator(),
            "op": "cancel-order",
            "args": [
                {
                    "instId": order_cancel.inst_id,
                    "ordId": order_cancel.order_id
                }
            ]
        }
        return json.dumps(msg, separators=(",", ":"))

    # OBJECT CONVERTERS
    def _object_from_json_public(self, msg: Dict) -> Any:
        channel = msg['arg']['channel']
        obj = None
        try:
            if channel.startswith('candle'):
                obj = self._candle_from_json(msg)
            else:
                logger.error(f'Unknown message PUBLIC: {msg}')
        except Exception as e:
            logger.error(f'Public processing object error: \n{msg}\n{e}', )
        return obj

    def _object_from_json_private(self, msg: Dict) -> Any:
        channel = msg['arg']['channel']
        obj = None
        try:
            if channel == 'account':
                obj = self._account_from_json(msg)
            elif channel == 'positions':
                obj = self._positions_from_json(msg)
            elif channel == 'orders':
                obj = self._fill_order_from_json(msg)
            else:
                logger.error(f'Unknown message PRIVATE: {msg}')
        except Exception as e:
            logger.error(f'Private processing object error: \n{msg}\n{e}', )
        return obj

    # TRADE API
    async def place_order(self, order: Order) -> OrderResponse:
        if not self.debug:
            await self.trade_ws.send(self._order_to_json(order))
            response = await self.trade_ws.recv()
            response = json.loads(response)
            order_response = self._order_response_from_json(response)
            return order_response
        logger.debug(f'Placing order: {order}')
        return OrderResponse(OrderStatus.ERROR)

    async def place_multiple_orders(self, orders: List[Order]):
        if not self.debug:
            await self.trade_ws.send(self._multiple_orders_to_json(orders))
            response = await self.trade_ws.recv()
            response = json.loads(response)
            orders_response = self._multiple_order_response_from_json(response)
            return orders_response
        logger.debug(f'Placing multiple order: {orders}')

    async def cancel_order(self, order_cancel: OrderCancel):
        await self.trade_ws.send(self._order_cancel_to_json(order_cancel))

    # ACC API
    async def set_leverage(self, inst_id: str, leverage: int, margin_mode: TradingMode):
        await self._set_leverage(instId=inst_id, lever=leverage, mgnMode=margin_mode)

    async def get_history_candles(self, ticker: str, tf: str, num_bars: int):
        candles = []
        for i in range((num_bars // 100) + 1):
            msg = await self._rest_get_history_candles(instId=ticker, bar=tf)
            candle = self._candle_from_json(msg, instId=ticker, timeframe=tf)
            candles.extend(candle[::-1])
        return candles[-num_bars:]

    async def get_instrument_info(self, inst_type: InstrumentType, uly: str = None, inst_id: str = None):
        msg = None
        if inst_type == InstrumentType.SPOT:
            msg = await self._rest_get_instrument_info(instType=inst_type.value, inst_id=inst_id)
        elif inst_type in [InstrumentType.SWAP]:
            msg = await self._rest_get_instrument_info(instType=inst_type.value, uly=uly)

        if msg is not None:
            instrument_info = self._instrument_info_from_json(msg)
            return instrument_info

    # REST API
    async def _place_order(self, **params):
        if self.debug:
            logger.warning(f'Placing order: {params}')
            return
        return await self._signed_rest_request(
            Method.POST, "/api/v5/trade/order", params=params
        )

    async def _set_leverage(self, **params):
        """https://www.okx.com/docs-v5/en/#rest-api-account-set-leverage"""
        return await self._signed_rest_request(Method.POST, "/api/v5/account/set-leverage", params=params)

    async def _rest_get_history_candles(self, **params) -> Dict:
        """https://www.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks-history"""
        return await self._signed_rest_request(Method.GET, "/api/v5/market/history-candles", params=params)

    async def _rest_get_instrument_info(self, **params):
        return await self._signed_rest_request(Method.GET, "/api/v5/public/instruments", params=params)

    def _get_headers(self, method: Method, path: str, params: Dict):
        timestamp = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
        return {
            "CONTENT-TYPE": "application/json",
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": self._get_signature(
                method=method, path=path, params=params, timestamp=timestamp
            ),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
        }

    async def _signed_rest_request(self, method: Method, path: str, params: Dict[str, Any]) -> Dict:
        headers = self._get_headers(method, path, params)
        if method == Method.GET:
            path = path + "?" + urlencode(params)

            async with self.rest_session.get(f"{self.rest_url}{path}", headers=headers, data={}) as result:
                return await handle_rest_response(result)

        elif method == Method.POST:
            async with self.rest_session.post(f"{self.rest_url}{path}", headers=headers, json=params) as result:
                return await handle_rest_response(result)

    #  WEBSOCKET SETUP
    def _get_signature(self, method: Method, path: str, params: Dict, timestamp: str):
        if params:
            if method == Method.GET:
                params = "?" + urlencode(params)
            else:
                params = json.dumps(params)
        else:
            params = ""
        message = timestamp + str(method) + path + params
        mac = hmac.new(
            self._secret_key.encode(), message.encode(), digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_login_msg(self):
        timestamp = int(time.time())
        msg = {
            "op": "login",
            "args": [
                {
                    "apiKey": f"{self._api_key}",
                    "passphrase": f"{self._passphrase}",
                    "timestamp": f"{timestamp}",
                    "sign": f"{self._get_signature(method='GET', path='/users/self/verify', params={}, timestamp=str(timestamp))}",
                },
            ]
        }
        return json.dumps(msg, separators=(",", ":"))

    async def _login(self, ws, ws_name: str):
        await ws.send(self._get_login_msg())
        response = await ws.recv()
        response = json.loads(response)
        if response.get('code') == '0':
            logger.info(f'Login success: {ws_name}')
        else:
            logger.error(f'Login error: {response.get("msg")}')

    def _get_subscribe_msg(self, channels):
        msg = {"op": "subscribe", "args": channels}
        return json.dumps(msg, separators=(",", ":"))

    async def _subscribe(self, ws, channels):
        logger.info(f'Subscribing to channels: {channels}')
        await ws.send(self._get_subscribe_msg(channels))
        for i in range(len(channels)):
            response = await ws.recv()
            response = json.loads(response)
            if response.get('event') == 'subscribe':
                logger.info(f'Subscribed: {response.get("arg")}')
            elif response.get('event') == 'error':
                logger.error(f'Subscribe error: {response.get("msg")}')
            else:
                logger.warning(f'Unknown subscribe message: {response}')

    async def _setup_public(self):
        self.public_ws = await websockets.connect(self.public_ws_url)
        await self._subscribe(self.public_ws, self.channels_public)
        logger.warning(f'Public setup done')

    async def _setup_private(self):
        self.private_ws = await websockets.connect(self.private_ws_url)
        await self._login(self.private_ws, 'PRIVATE')
        await self._subscribe(self.private_ws, self.channels_private)
        logger.warning(f'Private setup done')

    async def _setup_trade(self):
        self.trade_ws = await websockets.connect(self.trade_ws_url)
        await self._login(self.trade_ws, 'TRADE')
        logger.warning(f'Trade setup done')

    async def _periodicaly_reconnect(self):
        logger.warning(f"Created reconnect task with interval: {self.reconnect_interval} seconds")
        while True:
            await asyncio.sleep(self.reconnect_interval)
            try:
                logger.warning(f"Reconnecting according to interval: {self.reconnect_interval} seconds")
                await self._reconnect()
            except Exception as e:
                logger.error(f"Failed to reconnect: {e}")

    async def _reconnect(self):
        try:
            for task in self.listening_tasks:
                if task is not None and not task.done():
                    logger.debug(f"Cancelling listening task {task}")
                    task.cancel()
            for ws in [self.public_ws, self.private_ws, self.trade_ws]:
                if ws is not None and not ws.closed:
                    logger.debug(f"Closing connection {ws}")
                    await ws.close()
        except Exception as e:
            logger.error(f"Failed to disconnect from websocket: {e}")
        await self._setup()
        logger.debug(f"Number of current running tasks {len(asyncio.all_tasks())}")

    async def _ping_trade_ws(self):
        while True:
            await self.trade_ws.send('ping')
            resp = await self.trade_ws.recv()
            # logger.warning(f'GOT PIGN RESPONSE: {resp}')
            await asyncio.sleep(20)

    async def _setup(self):
        self.rest_session = aiohttp.ClientSession()

        await self._setup_public()
        await self._setup_private()
        await self._setup_trade()

        self.listening_tasks = [
            asyncio.create_task(self._listen_to_public_ws()),
            asyncio.create_task(self._listen_to_private_ws()),
            # asyncio.create_task(self._listen_to_trade_ws()),
            asyncio.create_task(self._ping_trade_ws()),
        ]

    async def run(self):
        await self._setup()
        # self.reconnect_task = asyncio.create_task(self._periodicaly_reconnect())

    async def exit(self):
        await self.rest_session.close()
        for ws in [self.public_ws, self.private_ws, self.trade_ws]:

            await ws.close()
        for task in [*self.listening_tasks, self.reconnect_task]:
            if not task.done():
                task.cancel()

