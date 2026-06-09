import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import yaml

LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "pipeline.log")
DBT_DIR = "dbt"
LLM_CONFIG = "config/llm.yml"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_log(source, status, message, details=None):
    os.makedirs(LOGS_DIR, exist_ok=True)
    entry = {
        "timestamp": _now(),
        "source": source,
        "status": status,
        "message": message,
        "details": details,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


# STUB: replace with real System 3 integration in phase 3
def notify_llm(entry):
    print(f"LLM routing: {entry}")


def _maybe_route_to_llm(entry):
    with open(LLM_CONFIG) as f:
        cfg = yaml.safe_load(f)
    if cfg.get("active"):
        notify_llm(entry)


try:
    import loader
except Exception as e:
    entry = _write_log("loader", "error", "Loader failed", str(e))
    _maybe_route_to_llm(entry)
    sys.exit(1)

_write_log("loader", "ok", "Loader completed successfully")

try:
    subprocess.run(
        ["dbt", "run", "--profiles-dir", "."],
        cwd=DBT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
except subprocess.CalledProcessError as e:
    entry = _write_log("dbt_run", "error", "dbt run failed", e.stdout or e.stderr)
    _maybe_route_to_llm(entry)
    sys.exit(1)

_write_log("dbt_run", "ok", "dbt run completed successfully")

try:
    subprocess.run(
        ["dbt", "test", "--profiles-dir", "."],
        cwd=DBT_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
except subprocess.CalledProcessError as e:
    entry = _write_log("dbt_test", "error", "dbt test failed", e.stdout or e.stderr)
    _maybe_route_to_llm(entry)
    sys.exit(1)

_write_log("dbt_test", "ok", "dbt test completed successfully")
