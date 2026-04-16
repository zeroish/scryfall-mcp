# Pinned 2026-04-15 — Docker Hardened Image (zero CVE)
FROM dhi.io/python:3.12@sha256:35924be4174348d4a0bdcf3bfaba81079cbb1faa52821611c71a6f50b3006572

ARG VERSION=dev

LABEL org.opencontainers.image.description="Scryfall MCP server for EDH/Commander" \
      org.opencontainers.image.source="https://github.com/zeroish/scryfall-mcp" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps as UID 0 so packages land in system site-packages (readable by all users)
USER 0
COPY requirements.txt .
RUN ["python3", "-m", "pip", "install", "--no-cache-dir", "--no-compile", "-r", "requirements.txt"]
COPY scryfall_mcp.py .

# Drop back to the hardened image's built-in nonroot user
USER nonroot

CMD ["python3", "scryfall_mcp.py"]
