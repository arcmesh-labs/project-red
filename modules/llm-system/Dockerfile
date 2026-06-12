FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "anthropic==0.109.1" \
    "PyGithub==2.9.1" \
    "dbt-duckdb==1.10.1" \
    "duckdb==1.5.3" \
    "pyyaml" \
    "python-dotenv"

WORKDIR /app
COPY . /app/modules/llm-system/
