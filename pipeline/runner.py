import json
import os
import subprocess
import sys
from datetime import datetime, timezone

LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "pipeline.log")
DBT_DIR = "dbt"


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


try:
    import loader
except Exception as e:
    _write_log("loader", "error", "Loader failed", str(e))
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
    _write_log("dbt_run", "error", "dbt run failed", e.stderr)
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
    _write_log("dbt_test", "error", "dbt test failed", e.stderr)
    sys.exit(1)

_write_log("dbt_test", "ok", "dbt test completed successfully")
