import asyncio

from Strategy.tutci import TutciStrategy
from Strategy.supertrend import SupertrendStrategy
from configs.config import config


async def main():
    strategy = SupertrendStrategy(config)
    await strategy.run()


if __name__ == '__main__':
    asyncio.run(main())
