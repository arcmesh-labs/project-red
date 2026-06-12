FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "dbt-duckdb==1.10.1" \
    "duckdb==1.5.3" \
    "pandas==2.3.3" \
    "anthropic==0.109.1" \
    "PyGithub==2.9.1" \
    "pyyaml" \
    "python-dotenv"

WORKDIR /app

COPY modules/pipeline/ modules/pipeline/
COPY modules/log-system/ modules/log-system/
COPY modules/llm-system/ modules/llm-system/

CMD ["python", "modules/log-system/runner.py"]
