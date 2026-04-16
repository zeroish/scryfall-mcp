import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP

# Config — override via environment for test doubles or staging mirrors
SCRYFALL_BASE_URL = os.environ.get("SCRYFALL_BASE_URL", "https://api.scryfall.com")

# Logs go to stderr — stdout is reserved for the MCP wire protocol
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_last_request_time: float = 0.0
_RATE_LIMIT_DELAY = 0.1  # 100ms between requests per Scryfall guidelines


@asynccontextmanager
async def lifespan(server):
    logger.info("scryfall-mcp starting")
    yield
    global _client
    if _client is not None:
        await _client.aclose()
        logger.info("HTTP client closed")


mcp = FastMCP("scryfall", lifespan=lifespan)


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={
                "User-Agent": "scryfall-mcp/0.1.0 (github.com/zeroish/scryfall-mcp)",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    return _client


async def scryfall_get(path: str, **params) -> dict:
    global _last_request_time

    elapsed = time.monotonic() - _last_request_time
    if elapsed < _RATE_LIMIT_DELAY:
        await asyncio.sleep(_RATE_LIMIT_DELAY - elapsed)

    client = get_client()
    url = f"{SCRYFALL_BASE_URL}{path}"
    logger.info("GET %s params=%s", path, params)
    _last_request_time = time.monotonic()
    response = await client.get(url, params=params)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    mcp.run()
