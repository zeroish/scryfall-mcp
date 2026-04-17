# Pinned 2026-04-15 — Docker Hardened Image (zero CVE)
# Stage 1: install deps into /deps so the runtime layer stays clean
FROM dhi.io/python:3.12@sha256:35924be4174348d4a0bdcf3bfaba81079cbb1faa52821611c71a6f50b3006572 AS builder

ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
USER 0
COPY requirements.txt .
RUN ["python3", "-m", "pip", "install", \
     "--no-cache-dir", "--no-compile", \
     "--target=/deps", \
     "-r", "requirements.txt"]

# Stage 2: minimal runtime — no pip artifacts, no build cache
FROM dhi.io/python:3.12@sha256:35924be4174348d4a0bdcf3bfaba81079cbb1faa52821611c71a6f50b3006572

ARG VERSION=dev

LABEL org.opencontainers.image.description="Scryfall MCP server for EDH/Commander" \
      org.opencontainers.image.source="https://github.com/zeroish/scryfall-mcp" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/deps \
    PATH="/deps/bin:$PATH"

WORKDIR /app

COPY --from=builder /deps /deps
COPY scryfall_mcp.py .

USER nonroot

# Default: stdio transport (for Claude Desktop / Claude Code)
# Override for SSE: docker run -p 8000:8000 scryfall-mcp python3 scryfall_mcp.py --sse
CMD ["python3", "scryfall_mcp.py"]
