FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONHASHSEED=0 \
    TZ=America/Detroit \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Layer-cache: install pip deps before copying source (hash-verified)
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Source directories
COPY common/ common/
COPY backtest/ backtest/
COPY tools/ tools/
COPY scripts/ scripts/
COPY wake_robin_data_pipeline/ wake_robin_data_pipeline/
COPY mcp_server/ mcp_server/
COPY adapters/ adapters/
COPY config/ config/
COPY tests/ tests/

# Top-level Python modules (run_screen imports many of these)
COPY *.py ./

# Package install (needs pyproject.toml + source in place)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python"]
