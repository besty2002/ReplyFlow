import asyncio
import logging

from app.workers.sync_bot import reconcile_all_shops

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def run_once():
    logger.info("ReplyFlow one-shot sync started")
    result = await reconcile_all_shops()
    logger.info("ReplyFlow one-shot sync finished: %s", result.get("summary"))
    return result


if __name__ == "__main__":
    asyncio.run(run_once())
