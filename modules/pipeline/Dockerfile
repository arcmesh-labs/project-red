FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "dbt-duckdb==1.10.1" \
    "duckdb==1.5.3" \
    "pandas==2.3.3" \
    "pyyaml" \
    "python-dotenv"

WORKDIR /app
COPY . /app/modules/pipeline/
