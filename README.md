# scryfall-mcp

An MCP server wrapping the [Scryfall API](https://scryfall.com/docs/api), built for EDH/Commander. Connects Claude Desktop, Claude Code, or any MCP client to Magic: The Gathering card data, rulings, prices, and combo discovery.

**Only dependency: Docker.**

---

## Quick start

### Claude Desktop (stdio)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "scryfall": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "ghcr.io/zeroish/scryfall-mcp"]
    }
  }
}
```

Or build locally first:

```bash
git clone https://github.com/zeroish/scryfall-mcp
cd scryfall-mcp
docker build -t scryfall-mcp .
```

Then use `scryfall-mcp` as the image name in the config above.

### Claude Code (stdio)

```bash
claude mcp add scryfall -- docker run -i --rm scryfall-mcp
```

### SSE / remote mode

```bash
docker compose up sse       # listens on :8000
# or
docker run -p 8000:8000 scryfall-mcp python3 scryfall_mcp.py --sse --port 8000
```

---

## Tools

### Core

| Tool | Description |
|------|-------------|
| `search_cards(query, page?)` | Full Scryfall syntax search — `c:blue cmc<=2 t:instant`, `o:draw f:commander`, etc. |
| `get_card(name)` | Fuzzy name lookup — typos and partial names work |
| `get_card_by_id(scryfall_id)` | Exact lookup by Scryfall UUID |
| `get_rulings(name)` | Official rulings with source and date |
| `get_prices(name)` | USD, USD foil, EUR, MTGO tix |
| `random_card(query?)` | Random card, optionally filtered |

### EDH / Commander

| Tool | Description |
|------|-------------|
| `commander_search(colors, theme?, card_types?)` | Find commanders by color identity, keyword theme, and/or type |
| `check_legality(card_name, format?)` | Legality check for any format — defaults to Commander |
| `parse_decklist(raw_text)` | Bulk-parse a pasted decklist, fetch all card data in batches |
| `find_combos(card_names)` | Combo discovery via Commander Spellbook |
| `get_set_cards(set_code, rarity?)` | All cards in a set — useful for cube curation and Pauper pools |

---

## Example prompts

```
Search for blue card draw spells under 3 mana that are Commander legal.

Parse this decklist and tell me the average mana value and color distribution:
[paste decklist]

What combos exist if my deck contains Thassa's Oracle, Demonic Consultation, and Tainted Pact?

Find me a Grixis commander that cares about the graveyard.

Is Jeweled Lotus legal in Commander? What about cEDH (duel)?

Show me all common blue instants in MH3 for my Pauper cube.

What are the official rulings on Rhystic Study?

How much does a foil Doubling Season cost right now?
```

---

## Configuration

All config is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRYFALL_BASE_URL` | `https://api.scryfall.com` | Override for test doubles or mirrors |
| `COMMANDERSPELLBOOK_URL` | `https://backend.commanderspellbook.com` | Override for staging |

---

## Development

```bash
# Hot-reload dev server (FastMCP inspector at localhost:6274)
docker compose up dev

# Rebuild the production image
make build

# Regenerate the pinned lockfile (requires pip-tools locally)
make deps
```

The `dev` service mounts `scryfall_mcp.py` as a read-only volume — edit the file and the inspector reloads without a rebuild.

---

## Architecture

- **Transport:** stdio (default) or SSE (`--sse` flag)
- **Rate limiting:** 100ms minimum between Scryfall requests, enforced server-side
- **Cache:** In-memory LRU (256 entries) for card name and ID lookups within a session
- **Base image:** [`dhi.io/python:3.12`](https://www.docker.com/products/hardened-images/) — Docker Hardened Image, zero CVEs
- **Build:** Multi-stage; dependencies installed in stage 1, only `/deps` + source copied to runtime

---

## License

MIT
