FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 1000 --no-create-home --shell /bin/false app

COPY scryfall_mcp.py .

USER app

CMD ["python", "scryfall_mcp.py"]
