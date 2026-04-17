.PHONY: bootstrap setup update server test cibuild console release deps

## bootstrap: install dependencies (build Docker image)
bootstrap:
	script/bootstrap

## setup: first-time project setup (calls bootstrap)
setup:
	script/setup

## update: rebuild image after pulling changes
update:
	script/update

## server: start the dev server with FastMCP inspector (http://localhost:6274)
server:
	script/server

## test: run the MCP smoke test suite inside Docker
##   make test              — run all tests
##   make test FILTER=get_card — run tests matching a name prefix
test:
	script/test $(FILTER)

## cibuild: CI entry point — build + test
cibuild:
	script/cibuild

## console: open a Python REPL inside the running container
console:
	script/console

## release: tag and push a release (triggers GitHub Actions build)
##   make release VERSION=v1.2.3
release:
	@test -n "$(VERSION)" || (echo "Usage: make release VERSION=v1.2.3" >&2; exit 1)
	script/release $(VERSION)

## deps: regenerate the pinned lockfile from requirements.in (requires pip-tools)
deps:
	pip-compile requirements.in -o requirements.txt
