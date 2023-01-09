import asyncio
import base64
import hashlib
import hmac
import random
import time
from typing import Dict, Any
from urllib.parse import urlencode
import websockets


from Structures.private import *
from Structures.public import *
from Structures.trade import *
from Tools.logger import Logger

logger = Logger(__name__).logger


def id_generator():
    return str(int(random.random() * 1000000) % 1000000)


class OkxConnection:
    def __init__(self, config, queue):
        self.reconnect_task = None
        self.reconnect_interval = 3600
        self.config = config
        self.queue = queue

        self.public_ws_url = self.config['okx_connection']['public_ws_url']
        self.private_ws_url = self.config['okx_connection']['private_ws_url']
        self.trade_ws_url = self.config['okx_connection']['trade_ws_url']
        self._api_key = self.config['api_key']
        self._secret_key = self.config['secret_key']
        self._passphrase = self.config['passphrase']
        self.channels_public = self.config['channels_public']
        self.channels_private = self.config['channels_private']

        self.public_ws = None
        self.private_ws = None
        self.trade_ws = None

        self.listening_tasks = []

    # WEBSOCKET LISTENERS
    async def listen_to_public_ws(self):
        while True:
            message = await self.public_ws.recv()
            msg_json = json.loads(message)
            obj = self.object_from_json_public(msg_json)
            self.queue.put_nowait(obj)

    async def listen_to_private_ws(self):
        while True:
            message = await self.private_ws.recv()
            msg_json = json.loads(message)
            obj = self.object_from_json_private(msg_json)
            self.queue.put_nowait(obj)

    async def listen_to_trade_ws(self):
        while True:
            message = await self.trade_ws.recv()
            msg_json = json.loads(message)
            obj = self.object_from_json_trade(msg_json)
            self.queue.put_nowait(obj)

    # JSON TO STRUCTURES CONVERTERS
    def _candle_from_json(self, msg: json) -> Candle:
        data = msg['data'][0]
        candle = Candle(
            inst_id=msg['arg']['instId'],
            timestamp_ms=int(data[0]),
            datetime=datetime.fromtimestamp(int(data[0]) // 1000),
            timeframe=msg['arg']['channel'].replace('candle', ''),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5]),
        )
        return candle

    def _positions_from_json(self, msg: json) -> Positions:
        positions = []
        for data in msg['data']:
            pos = Position(
                side=Side.LONG if data['posSide'] == 'long' else Side.SHORT,
                ccy=data['ccy'],
                instrument_type=InstrumentType.SWAP,
                size=float(data['pos']),
                upl=float(data['upl'])
            )
            positions.append(pos)
        return Positions(positions=positions, datetime=datetime.now())

    def _account_from_json(self, msg: json) -> Account:
        coins = []
        timestamp_ms = int(msg['data'][0]['uTime'])
        dt = datetime.fromtimestamp(timestamp_ms // 1000)
        total_usd = 0
        for data in msg['data'][0]['details']:
            coin = CoinBalance(
                ccy=data['ccy'],
                equity=float(data['eq'])
            )
            total_usd += float(data['eq'])
            coins.append(coin)
        return Account(coins=coins, datetime=dt, total_usd=total_usd)

    def _order_response_from_json(self, msg: json) -> OrderResponse:
        return OrderResponse(
            op=msg['op'],
            order_id=msg['data'][0]['ordId'],
            status=OrderStatus.OK if msg['code'] == '0' else OrderStatus.ERROR,
            data=msg['data']
        )

    def _fill_order_from_json(self, msg: json) -> FillOrder:
        data = msg['data'][0]
        fill_order = FillOrder(
            ticker=data['instId'],
            inst_type=InstrumentType.SWAP,
            posSide=Side.LONG if data['posSide'] == 'long' else Side.SHORT if data['posSide'] == 'short' else None,
            action=Action.BUY if data['side'] == 'buy' else Action.SELL,
            size=float(data['sz']),
            fill_price=float(data['fillPx']),
            fill_time=datetime.fromtimestamp(int(data['fillTime']) // 1000),
            state=data['state'],
            leverage=float(data['lever']),
            fee=float(data['fee']),
            pnl=float(data['pnl']),
            create_time=datetime.fromtimestamp(int(data['cTime']) // 1000)
        )

        return fill_order

    # OBJECT CONVERTERS
    def object_from_json_public(self, msg: json) -> Any:
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

    def object_from_json_private(self, msg: json) -> Any:
        channel = msg['arg']['channel']
        obj = None
        try:
            if channel == 'account':
                obj = self._account_from_json(msg)
            elif channel == 'positions':
                obj = self._positions_from_json(msg)  # Positions().from_json(msg)
            elif channel == 'orders':
                obj = self._fill_order_from_json(msg)
                logger.warning(msg)
            else:
                logger.error(f'Unknown message PRIVATE: {msg}')
        except Exception as e:
            logger.error(f'Private processing object error: \n{msg}\n{e}', )
        return obj

    def object_from_json_trade(self, msg: json) -> Any:
        op = msg['op']
        obj = None
        try:
            if op in ['order', 'cancel-order']:
                obj = self._order_response_from_json(msg)
            else:
                logger.error(f'Unknown message TRADE: {msg}')
        except Exception as e:
            logger.error(f'Trade processing object error: \n{msg}\n{e}', )
        return obj

    # REQUESTS

    async def place_order(self, order: Order):
        await self.trade_ws.send(self._get_order_msg(order))
        # pass

    async def cancel_order(self, order_cancel: OrderCancel):
        await self.trade_ws.send(self._get_order_cancel_msg(order_cancel))

    #  SETUP
    def _get_order_cancel_msg(self, order_cancel: OrderCancel):
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

    def _get_order_msg(self, order: Order) -> json:  # TODO: long/short or buy/sell account setting
        pos_side_map = {Side.LONG: 'long', Side.SHORT: 'short'}
        action_map = {Action.BUY: 'buy', Action.SELL: 'sell'}
        tdMode_map = {TradingMode.CROSS: 'cross', TradingMode.ISOLATED: 'isolated', TradingMode.CASH: 'cash'}
        ordType_map = {OrderType.MARKET: 'market', OrderType.LIMIT: 'limit'}

        msg = {
            "id": id_generator(),
            "op": "order",
            "args": [
                {
                    "side": action_map[order.action],
                    "instId": order.ticker,
                    "tdMode": tdMode_map[order.trading_mode],
                    "ordType": ordType_map[order.order_type],
                    "sz": order.size
                }
            ]
        }
        return json.dumps(msg, separators=(",", ":"))

    def _get_login_signature(self, method: str, path: str, params: Dict, timestamp: str):
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
                    "sign": f"{self._get_login_signature(method='GET', path='/users/self/verify', params={}, timestamp=str(timestamp))}",
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

    async def _setup_private(self):
        self.private_ws = await websockets.connect(self.private_ws_url)
        await self._login(self.private_ws, 'PRIVATE')
        await self._subscribe(self.private_ws, self.channels_private)

    async def _setup_trade(self):
        self.trade_ws = await websockets.connect(self.trade_ws_url)
        await self._login(self.trade_ws, 'TRADE')

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
        await self.setup()
        logger.debug(f"Number of current running tasks {len(asyncio.all_tasks())}")

    async def setup(self):
        await self._setup_public()
        await self._setup_private()
        await self._setup_trade()

        self.listening_tasks = [
            asyncio.create_task(self.listen_to_public_ws()),
            asyncio.create_task(self.listen_to_private_ws()),
            asyncio.create_task(self.listen_to_trade_ws())
        ]

    async def run(self):
        await self.setup()
        self.reconnect_task = asyncio.create_task(self._periodicaly_reconnect())
