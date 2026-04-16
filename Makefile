.PHONY: build dev deps

# Build the production image
build:
	docker compose build scryfall-mcp

# Run the FastMCP inspector (hot-reload, source mounted)
dev:
	docker compose up dev

# Regenerate the pinned lockfile from requirements.in
# Requires pip-tools: pip install pip-tools
deps:
	pip-compile requirements.in -o requirements.txt
