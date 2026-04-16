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

    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            detail = e.response.json().get("details", str(e))
        except Exception:
            detail = str(e)
        if status == 404:
            raise LookupError(detail) from None
        if status == 429:
            raise RuntimeError("Rate limited by Scryfall — please wait a moment and retry.") from None
        raise RuntimeError(f"Scryfall API error {status}: {detail}") from None

    return response.json()


def _format_card(card: dict) -> dict:
    """Flatten a Scryfall card object to a clean, consistent dict."""
    # Double-faced cards store oracle_text and mana_cost on each face
    faces = card.get("card_faces")
    if faces:
        oracle_text = " // ".join(f.get("oracle_text", "") for f in faces)
        mana_cost = " // ".join(f.get("mana_cost", "") for f in faces if f.get("mana_cost"))
    else:
        oracle_text = card.get("oracle_text", "")
        mana_cost = card.get("mana_cost", "")

    return {
        "id": card.get("id", ""),
        "name": card.get("name", ""),
        "mana_cost": mana_cost,
        "type_line": card.get("type_line", ""),
        "oracle_text": oracle_text,
        "colors": card.get("colors", []),
        "color_identity": card.get("color_identity", []),
        "legalities": card.get("legalities", {}),
        "prices": card.get("prices", {}),
        "scryfall_uri": card.get("scryfall_uri", ""),
        "set": card.get("set", ""),
        "set_name": card.get("set_name", ""),
        "rarity": card.get("rarity", ""),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def search_cards(query: str, page: int = 1) -> list[dict]:
    """Search for Magic cards using full Scryfall syntax.

    Examples: 'c:blue cmc<=2 t:instant', 'o:draw t:sorcery f:commander',
    'id<=WUBR is:commander'. Returns up to 175 results per page.
    """
    try:
        data = await scryfall_get("/cards/search", q=query, page=page)
    except LookupError:
        return []
    return [_format_card(c) for c in data.get("data", [])]


@mcp.tool
async def get_card(name: str) -> dict:
    """Get a card by name using fuzzy matching.

    Returns the closest match to the provided name. Prefer this over
    get_card_by_id when you have a card name but not an exact UUID.
    """
    return _format_card(await scryfall_get("/cards/named", fuzzy=name))


@mcp.tool
async def get_card_by_id(scryfall_id: str) -> dict:
    """Get a card by its Scryfall UUID."""
    return _format_card(await scryfall_get(f"/cards/{scryfall_id}"))


@mcp.tool
async def get_rulings(name: str) -> list[dict]:
    """Get official rulings for a card by name.

    Returns a list of rulings with source and published_at fields.
    """
    card = await scryfall_get("/cards/named", fuzzy=name)
    data = await scryfall_get(f"/cards/{card['id']}/rulings")
    return [
        {
            "source": r.get("source", ""),
            "published_at": r.get("published_at", ""),
            "comment": r.get("comment", ""),
        }
        for r in data.get("data", [])
    ]


@mcp.tool
async def get_prices(name: str) -> dict:
    """Get current market prices for a card by name.

    Returns USD, USD foil, EUR, and MTGO tix prices where available.
    """
    card = await scryfall_get("/cards/named", fuzzy=name)
    return {
        "name": card.get("name", ""),
        "set": card.get("set", ""),
        "set_name": card.get("set_name", ""),
        "collector_number": card.get("collector_number", ""),
        "prices": card.get("prices", {}),
        "scryfall_uri": card.get("scryfall_uri", ""),
    }


@mcp.tool
async def random_card(query: str = "") -> dict:
    """Get a random Magic card, optionally filtered by a Scryfall query.

    Examples: query='t:dragon f:commander', query='c:green cmc=3'
    """
    params = {"q": query} if query else {}
    return _format_card(await scryfall_get("/cards/random", **params))


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    mcp.run()
