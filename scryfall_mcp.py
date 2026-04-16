import asyncio
import logging
import os
import re
import signal
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP

# Config — override via environment for test doubles or staging mirrors
SCRYFALL_BASE_URL = os.environ.get("SCRYFALL_BASE_URL", "https://api.scryfall.com")
COMMANDERSPELLBOOK_URL = os.environ.get(
    "COMMANDERSPELLBOOK_URL", "https://backend.commanderspellbook.com"
)

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


async def scryfall_post(path: str, body: dict) -> dict:
    global _last_request_time

    elapsed = time.monotonic() - _last_request_time
    if elapsed < _RATE_LIMIT_DELAY:
        await asyncio.sleep(_RATE_LIMIT_DELAY - elapsed)

    client = get_client()
    url = f"{SCRYFALL_BASE_URL}{path}"
    logger.info("POST %s", path)
    _last_request_time = time.monotonic()

    try:
        response = await client.post(url, json=body)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            detail = e.response.json().get("details", str(e))
        except Exception:
            detail = str(e)
        if status == 429:
            raise RuntimeError("Rate limited by Scryfall — please wait a moment and retry.") from None
        raise RuntimeError(f"Scryfall API error {status}: {detail}") from None

    return response.json()


def _format_card(card: dict) -> dict:
    """Flatten a Scryfall card object to a clean, consistent dict."""
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


# Matches: "4 Lightning Bolt", "4x Lightning Bolt", "1 Sol Ring (C21) 263"
_DECKLIST_RE = re.compile(
    r"^\s*(\d+)x?\s+(.+?)(?:\s+\([A-Z0-9a-z]+\)\s+\S+)?\s*$"
)


def _parse_decklist_lines(raw_text: str) -> list[tuple[int, str]]:
    entries = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        m = _DECKLIST_RE.match(line)
        if m:
            entries.append((int(m.group(1)), m.group(2).strip()))
    return entries


# ---------------------------------------------------------------------------
# Phase 2 — Core Tools
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


# ---------------------------------------------------------------------------
# Phase 3 — EDH-Specific Tools
# ---------------------------------------------------------------------------

@mcp.tool
async def commander_search(
    colors: list[str],
    theme: str = "",
    card_types: str = "",
) -> list[dict]:
    """Find commanders matching a color identity, optional theme, and optional type.

    Args:
        colors: Color identity as a list of single letters, e.g. ["W","U","B"].
                Use [] for colorless.
        theme: Optional Scryfall keyword theme, e.g. "draw", "tokens", "sacrifice".
        card_types: Optional creature type filter, e.g. "elf", "dragon", "wizard".

    Builds a Scryfall query like `id<=WUB is:commander k:draw t:elf` automatically.
    Returns up to 175 matching commanders sorted by EDHREC rank.
    """
    color_str = "".join(c.upper() for c in colors) if colors else "C"
    parts = [f"id<={color_str}", "is:commander"]
    if theme:
        parts.append(f"k:{theme}")
    if card_types:
        parts.append(f"t:{card_types}")

    query = " ".join(parts)
    try:
        data = await scryfall_get("/cards/search", q=query, order="edhrec")
    except LookupError:
        return []
    return [_format_card(c) for c in data.get("data", [])]


@mcp.tool
async def check_legality(card_name: str, format: str = "commander") -> dict:
    """Check whether a card is legal in a given format.

    Args:
        card_name: Card name (fuzzy matched).
        format: Format to check — e.g. 'commander', 'pauper', 'legacy',
                'modern', 'standard', 'vintage', 'pioneer'. Defaults to 'commander'.

    Returns legality status ('legal', 'banned', 'restricted', 'not_legal')
    plus the full legalities table for reference.
    """
    card = await scryfall_get("/cards/named", fuzzy=card_name)
    legalities = card.get("legalities", {})
    status = legalities.get(format.lower(), "unknown")

    _status_labels = {
        "legal": "Legal",
        "banned": "Banned",
        "restricted": "Restricted (limit 1 copy)",
        "not_legal": "Not legal in this format",
        "unknown": f"Unknown format '{format}'",
    }

    return {
        "name": card.get("name", ""),
        "format": format.lower(),
        "status": status,
        "summary": _status_labels.get(status, status),
        "legalities": legalities,
        "scryfall_uri": card.get("scryfall_uri", ""),
    }


@mcp.tool
async def parse_decklist(raw_text: str) -> dict:
    """Parse a pasted decklist and fetch full card data for each entry.

    Accepts standard decklist formats:
      - "4 Lightning Bolt"
      - "4x Lightning Bolt"
      - "1 Sol Ring (C21) 263"

    Fetches cards in batches of 75 via Scryfall's /cards/collection endpoint.
    Returns found cards (with quantities) and a list of any names not found.
    """
    entries = _parse_decklist_lines(raw_text)
    if not entries:
        return {"found": [], "not_found": [], "parse_errors": []}

    # Deduplicate names for fetching; preserve quantities separately
    name_to_qty: dict[str, int] = {}
    for qty, name in entries:
        name_to_qty[name] = name_to_qty.get(name, 0) + qty

    unique_names = list(name_to_qty.keys())

    # Batch into groups of 75 (Scryfall's collection limit)
    found_cards: list[dict] = []
    not_found: list[str] = []

    for i in range(0, len(unique_names), 75):
        batch = unique_names[i : i + 75]
        identifiers = [{"name": n} for n in batch]
        data = await scryfall_post("/cards/collection", {"identifiers": identifiers})
        for card in data.get("data", []):
            name = card.get("name", "")
            formatted = _format_card(card)
            formatted["quantity"] = name_to_qty.get(name, 1)
            found_cards.append(formatted)
        for nf in data.get("not_found", []):
            not_found.append(nf.get("name", str(nf)))

    return {
        "found": found_cards,
        "not_found": not_found,
        "total_cards": sum(name_to_qty.values()),
        "unique_cards": len(unique_names),
    }


@mcp.tool
async def find_combos(card_names: list[str]) -> list[dict]:
    """Find combos from Commander Spellbook that exist within a given card pool.

    Input a list of card names from your deck. Returns any known combos
    that can be assembled from those cards, with steps and requirements.
    """
    if not card_names:
        return []

    client = get_client()
    # Commander Spellbook /variants/ accepts card:"Name" syntax
    q = " ".join(f'card:"{name}"' for name in card_names)
    url = f"{COMMANDERSPELLBOOK_URL}/variants/"
    logger.info("GET variants cards=%d", len(card_names))

    try:
        response = await client.get(url, params={"q": q})
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Commander Spellbook API error {e.response.status_code}"
        ) from None

    data = response.json()
    combos = []
    for combo in data.get("results", []):
        uses = [u.get("card", {}).get("name", "") for u in combo.get("uses", [])]
        produces = [p.get("feature", {}).get("name", "") for p in combo.get("produces", [])]
        combos.append({
            "id": combo.get("id", ""),
            "uses": uses,
            "produces": produces,
            "prerequisites": combo.get("easyPrerequisites", "") or combo.get("notablePrerequisites", ""),
            "steps": combo.get("description", ""),
            "spellbook_uri": f"https://commanderspellbook.com/combo/{combo.get('id', '')}",
        })
    return combos


@mcp.tool
async def get_set_cards(set_code: str, rarity: str = "") -> list[dict]:
    """Get all cards in a set, optionally filtered by rarity.

    Args:
        set_code: Three-to-five letter set code, e.g. 'mh3', 'c21', 'dsk'.
        rarity: Optional rarity filter — 'common', 'uncommon', 'rare', 'mythic'.
                Leave empty for all rarities.

    Useful for cube curation, pauper/peasant pool building, and set review.
    Fetches all pages automatically.
    """
    parts = [f"e:{set_code.lower()}"]
    if rarity:
        parts.append(f"r:{rarity.lower()}")
    query = " ".join(parts)

    cards: list[dict] = []
    page = 1
    while True:
        try:
            data = await scryfall_get("/cards/search", q=query, page=page, order="set")
        except LookupError:
            break
        cards.extend(_format_card(c) for c in data.get("data", []))
        if not data.get("has_more"):
            break
        page += 1

    return cards


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    mcp.run()
