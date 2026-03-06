FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONHASHSEED=0 \
    TZ=America/Detroit \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Layer-cache: install pip deps before copying source
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source directories
COPY common/ common/
COPY tools/ tools/
COPY scripts/ scripts/
COPY wake_robin_data_pipeline/ wake_robin_data_pipeline/
COPY mcp_server/ mcp_server/
COPY adapters/ adapters/
COPY config/ config/
COPY tests/ tests/

# Top-level entry points and modules
COPY run_screen.py decision_engine.py archive_snapshot.py __init__.py ./
COPY production_validation.py decision_engine_codes.py event_detector.py ctgov_adapter.py ./

# Package install (needs pyproject.toml + source in place)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python"]
