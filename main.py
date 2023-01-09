import asyncio

from Strategy.tutci import TutciStrategy
from configs.config import config


async def main():
    strategy = TutciStrategy(config)
    await strategy.run()


if __name__ == '__main__':
    asyncio.run(main())
