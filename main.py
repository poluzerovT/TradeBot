import asyncio
from Strategy.supertrend import SupertrendStrategy
from configs.config import config


async def main():
    strat = SupertrendStrategy(config, debug=False)
    await strat.run()


if __name__ == '__main__':
    asyncio.run(main())