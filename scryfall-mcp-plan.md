# Scryfall MCP Server — Build Plan

## Overview

A custom Python MCP server wrapping the [Scryfall API](https://scryfall.com/docs/api), purpose-built for EDH/Commander use cases: deck analysis, combo discovery, cube tooling, and the dorks.rocks league ecosystem.

**Stack:** Python · `fastmcp` · `httpx`  
**Transport:** stdio (primary) · SSE (optional, for remote use)  
**Target clients:** Claude Desktop, Claude Code, dorks.rocks

---

## Reference

- Scryfall API docs: https://scryfall.com/docs/api
- Commander Spellbook API: https://commanderspellbook.com/api/v2/
- fastmcp docs: https://github.com/jlowin/fastmcp
- Inspiration (do not copy): https://github.com/cryppadotta/scryfall-mcp

---

## Phase 1 — Scaffold

**Goal:** Bare-bones server that runs and responds to MCP handshake.

### Tasks
- [ ] Create project directory `scryfall-mcp/`
- [ ] Set up `pyproject.toml` or `requirements.txt` with dependencies:
  - `fastmcp`
  - `httpx`
- [ ] Create `scryfall_mcp.py` with a `FastMCP` app instance
- [ ] Define Scryfall base URL constant: `https://api.scryfall.com`
- [ ] Add a shared `httpx.AsyncClient` with polite headers (`User-Agent`, `Accept: application/json`)
- [ ] Implement rate-limit helper: enforce ~100ms delay between requests per Scryfall guidelines
- [ ] Verify server starts and responds via `fastmcp dev scryfall_mcp.py`

### Deliverable
Running MCP server with no tools yet — just a clean scaffold.

---

## Phase 2 — Core Tools

**Goal:** Cover the same surface area as existing open-source options.

### Tools to implement

| Tool | Scryfall Endpoint | Notes |
|------|-------------------|-------|
| `search_cards(query, page?)` | `GET /cards/search?q=` | Full Scryfall syntax support |
| `get_card(name)` | `GET /cards/named?fuzzy=` | Fuzzy match preferred |
| `get_card_by_id(id)` | `GET /cards/{id}` | Scryfall UUID |
| `get_rulings(name)` | `GET /cards/named?fuzzy=` → `/cards/{id}/rulings` | Two-step lookup |
| `get_prices(name)` | `GET /cards/named?fuzzy=` | Extract `prices` object |
| `random_card(query?)` | `GET /cards/random?q=` | Optional filter query |

### Notes
- Return clean, flattened dicts — not raw Scryfall JSON blobs
- Include `name`, `mana_cost`, `type_line`, `oracle_text`, `colors`, `color_identity`, `legalities`, `prices`, `scryfall_uri` in all card responses
- Handle 404s and rate-limit (429) errors gracefully with meaningful messages

### Deliverable
All 6 tools working and testable via Claude Desktop.

---

## Phase 3 — EDH-Specific Tools

**Goal:** The differentiator. Tools no existing server provides out of the box.

### Tools to implement

#### `commander_search(colors, theme?, card_types?)`
- Input: color identity as list (e.g. `["W","U","B"]`), optional theme keyword, optional type filter
- Build a Scryfall query like `id<=WUB f:commander k:draw` automatically
- Return top matching commanders with brief summaries

#### `check_legality(card_name, format?)`
- Default format: `commander`
- Return legality status + reason if banned/restricted
- Bonus: flag cards on the Commander RC watchlist

#### `parse_decklist(raw_text)`
- Accept pasted decklist in standard formats:
  - `4 Lightning Bolt`
  - `4x Lightning Bolt`
  - `1 Sol Ring (C21) 263`
- Bulk-fetch all cards via Scryfall `/cards/collection` endpoint (up to 75 at a time)
- Return full card objects for each entry
- Flag any cards not found

#### `find_combos(card_names)`
- Hit Commander Spellbook API: `GET https://backend.commanderspellbook.com/find-my-combos/`
- Input: list of card names in the deck
- Return combos that exist within that card pool, with steps and requirements

#### `get_set_cards(set_code, rarity?)`
- Useful for cube curation
- Fetch all cards in a set, optionally filtered by rarity (`common`, `uncommon`, etc.)
- Supports Pauper/Peasant cube workflows

### Deliverable
All 5 tools working. `parse_decklist` + `find_combos` should be demonstrable end-to-end with a real Commander decklist.

---

## Phase 4 — Polish & Deploy

**Goal:** Production-ready, portable, documented.

### Tasks

#### Code quality
- [ ] Add `pydantic` models for card/ruling/price response shapes
- [ ] Add input validation (color identity values, set codes, etc.)
- [ ] Centralize error handling — all tools return structured errors, never raw exceptions

#### Rate limiting & caching
- [ ] Enforce Scryfall's requested 50–100ms between requests
- [ ] Add in-memory LRU cache for card lookups (avoid re-fetching the same card in a session)

#### Docker
- [ ] Create `Dockerfile`
- [ ] Multi-stage build: slim Python base, no dev deps in final image
- [ ] Support `CMD` override for SSE mode: `python scryfall_mcp.py --sse`

#### Configuration (`claude_desktop_config.json` snippets)
```json
// stdio (local)
{
  "mcpServers": {
    "scryfall": {
      "command": "python",
      "args": ["/path/to/scryfall-mcp/scryfall_mcp.py"]
    }
  }
}

// Docker
{
  "mcpServers": {
    "scryfall": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "scryfall-mcp"]
    }
  }
}
```

#### Documentation
- [ ] `README.md` with setup, tool reference, and example prompts
- [ ] Example prompts section (see below)

#### Optional: SSE mode for dorks.rocks
- [ ] Add `--sse` flag to expose HTTP endpoints
- [ ] `GET /sse` — event stream
- [ ] `POST /messages` — message handler
- [ ] Deploy to a lightweight EC2/Fargate task or Lambda (if low traffic)

---

## Example Prompts (for README)

```
Search for blue card draw spells under 3 mana that are Commander legal.

Parse this decklist and tell me the average mana value and color distribution:
[paste decklist]

What combos exist in my Kaalia of the Vast deck?

Find me a Grixis commander that cares about the graveyard.

Is Jeweled Lotus legal in Commander? What about cEDH?

Show me all common blue instants in MH3 for my Pauper cube.
```

---

## Future Ideas (Backlog)

- `suggest_upgrades(decklist, budget?)` — find budget replacements or power-ups for cards in a list
- `color_pie_analysis(decklist)` — break down spells by color, type, and function
- `price_check_decklist(decklist)` — total TCGPlayer/Card Kingdom value of a list
- Discord bot integration (reuse tool logic, wrap in discord.py)
- Persistent card index for the dorks.rocks league (track cube card pool, owned inventory)
