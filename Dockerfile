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

# Source (.dockerignore controls exclusions — data/, cache/, output/, etc.)
COPY . .

# Editable install (needs source + pyproject.toml in place)
RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python"]
