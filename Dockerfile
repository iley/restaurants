FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Download pmtiles CLI for tile extraction
ADD https://github.com/protomaps/go-pmtiles/releases/download/v1.22.5/go-pmtiles_1.22.5_Linux_x86_64.tar.gz /tmp/pmtiles.tar.gz
RUN tar -xzf /tmp/pmtiles.tar.gz -C /tmp && mv /tmp/pmtiles /usr/local/bin/pmtiles && rm /tmp/pmtiles.tar.gz


FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /app /app
COPY --from=builder /usr/local/bin/pmtiles /usr/local/bin/pmtiles
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
