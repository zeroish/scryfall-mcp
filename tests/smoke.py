#!/usr/bin/env python3
"""MCP smoke test — spawns the server as a subprocess and exercises all tools.

Runs inside the application Docker image (python3 /smoke.py).
Accepts an optional name-prefix filter argument:
  python3 /smoke.py get_card   # only run tests whose name starts with get_card
"""

import json
import queue
import subprocess
import sys
import threading
import time

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"
PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"

NAME_FILTER = sys.argv[1] if len(sys.argv) > 1 else ""


def main():
    proc = subprocess.Popen(
        ["python3", "/app/scryfall_mcp.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    q: queue.Queue = queue.Queue()

    def reader():
        for line in proc.stdout:
            line = line.strip()
            if line:
                q.put(line)

    threading.Thread(target=reader, daemon=True).start()

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg).encode() + b"\n")
        proc.stdin.flush()

    def recv(timeout: float = 15.0) -> dict:
        return json.loads(q.get(timeout=timeout))

    # MCP handshake
    send({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0"},
        },
    })
    recv()
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    time.sleep(0.6)

    _id = [2]

    def call(tool: str, args: dict, timeout: float = 20.0):
        """Call a tool and return (is_error: bool, payload: str | dict)."""
        send({
            "jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        })
        resp = recv(timeout=timeout)
        _id[0] += 1
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content_items = result.get("content", [])
        if not content_items:
            # FastMCP returns empty content for tools that return [] or None
            return is_error, None
        text = content_items[0].get("text", "")
        if is_error:
            return True, text
        return False, json.loads(text)

    # ------------------------------------------------------------------ tests

    def test_search_cards():
        err, r = call("search_cards", {"query": "c:blue cmc<=1 t:instant"})
        assert not err, r
        assert isinstance(r, list) and len(r) > 0
        assert all("name" in c for c in r)

    def test_get_card():
        err, r = call("get_card", {"name": "Sol Ring"})
        assert not err, r
        assert r["name"] == "Sol Ring"
        assert "{1}" in r["mana_cost"]

    def test_get_card_by_id():
        _, card = call("get_card", {"name": "Lightning Bolt"})
        err, r = call("get_card_by_id", {"scryfall_id": card["id"]})
        assert not err, r
        assert r["name"] == "Lightning Bolt"

    def test_get_card_cache():
        # Second call for the same name should hit cache (no observable difference,
        # just verify the result is still correct)
        err, r = call("get_card", {"name": "Sol Ring"})
        assert not err, r
        assert r["name"] == "Sol Ring"

    def test_get_rulings():
        err, r = call("get_rulings", {"name": "Rhystic Study"})
        assert not err, r
        assert isinstance(r, list) and len(r) > 0
        assert all("comment" in x for x in r)

    def test_get_prices():
        err, r = call("get_prices", {"name": "Sol Ring"})
        assert not err, r
        assert r["name"] == "Sol Ring"
        assert "usd" in r["prices"]

    def test_random_card():
        err, r = call("random_card", {"query": "t:dragon"})
        assert not err, r
        assert "Dragon" in r["type_line"]

    def test_commander_search():
        err, r = call("commander_search", {"colors": ["U", "B"], "theme": "draw"})
        assert not err, r
        assert isinstance(r, list) and len(r) > 0

    def test_commander_search_colorless():
        err, r = call("commander_search", {"colors": []})
        assert not err, r
        assert isinstance(r, list)

    def test_commander_search_invalid_color():
        err, r = call("commander_search", {"colors": ["X"]})
        assert err, "Expected error for invalid color"

    def test_check_legality_banned():
        err, r = call("check_legality", {"card_name": "Black Lotus", "format": "commander"})
        assert not err, r
        assert r["status"] == "banned"

    def test_check_legality_legal():
        err, r = call("check_legality", {"card_name": "Sol Ring", "format": "commander"})
        assert not err, r
        assert r["status"] == "legal"

    def test_check_legality_invalid_format():
        err, r = call("check_legality", {"card_name": "Sol Ring", "format": "fakefmt"})
        assert err, "Expected error for unknown format"

    def test_parse_decklist():
        err, r = call("parse_decklist", {
            "raw_text": "1 Sol Ring\n1 Lightning Bolt\n1 Counterspell"
        })
        assert not err, r
        assert r["total_cards"] == 3
        assert r["unique_cards"] == 3
        assert len(r["found"]) == 3

    def test_parse_decklist_with_set():
        err, r = call("parse_decklist", {"raw_text": "1 Sol Ring (C21) 263"})
        assert not err, r
        assert r["total_cards"] == 1
        assert len(r["found"]) == 1

    def test_parse_decklist_empty():
        err, r = call("parse_decklist", {"raw_text": "# just a comment\n"})
        assert not err, r
        assert r["total_cards"] == 0
        assert r["found"] == []

    def test_find_combos():
        err, r = call("find_combos", {
            "card_names": ["Thassa's Oracle", "Demonic Consultation"]
        }, timeout=30)
        assert not err, r
        assert isinstance(r, list) and len(r) > 0
        assert all("uses" in c and "steps" in c for c in r)

    def test_find_combos_empty():
        err, r = call("find_combos", {"card_names": []})
        assert not err, r
        assert not r  # empty list or no content

    def test_get_set_cards():
        err, r = call("get_set_cards", {"set_code": "lea", "rarity": "rare"}, timeout=60)
        assert not err, r
        assert isinstance(r, list) and len(r) > 0
        assert all(c["rarity"] == "rare" for c in r)

    def test_get_set_cards_invalid_rarity():
        err, r = call("get_set_cards", {"set_code": "mh3", "rarity": "super-rare"})
        assert err, "Expected error for invalid rarity"

    def test_get_set_cards_invalid_code():
        err, r = call("get_set_cards", {"set_code": "!!!!!"})
        assert err, "Expected error for invalid set code"

    # ------------------------------------------------------------------ runner

    tests = [
        ("search_cards", test_search_cards),
        ("get_card", test_get_card),
        ("get_card_by_id", test_get_card_by_id),
        ("get_card (cache)", test_get_card_cache),
        ("get_rulings", test_get_rulings),
        ("get_prices", test_get_prices),
        ("random_card", test_random_card),
        ("commander_search", test_commander_search),
        ("commander_search (colorless)", test_commander_search_colorless),
        ("commander_search (invalid color)", test_commander_search_invalid_color),
        ("check_legality (banned)", test_check_legality_banned),
        ("check_legality (legal)", test_check_legality_legal),
        ("check_legality (invalid format)", test_check_legality_invalid_format),
        ("parse_decklist", test_parse_decklist),
        ("parse_decklist (set notation)", test_parse_decklist_with_set),
        ("parse_decklist (empty)", test_parse_decklist_empty),
        ("find_combos", test_find_combos),
        ("find_combos (empty)", test_find_combos_empty),
        ("get_set_cards", test_get_set_cards),
        ("get_set_cards (invalid rarity)", test_get_set_cards_invalid_rarity),
        ("get_set_cards (invalid code)", test_get_set_cards_invalid_code),
    ]

    if NAME_FILTER:
        tests = [(n, fn) for n, fn in tests if n.startswith(NAME_FILTER)]
        if not tests:
            print(f"No tests match filter '{NAME_FILTER}'")
            sys.exit(1)

    results = []
    print(f"\nRunning {len(tests)} test(s)...\n")

    for name, fn in tests:
        try:
            fn()
            results.append((name, True, None))
            print(f"  {PASS}  {name}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  {FAIL}  {name}: {e}")

    proc.terminate()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} passed")

    if passed < total:
        print("\nFailed tests:")
        for name, ok, err in results:
            if not ok:
                print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
