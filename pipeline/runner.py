import json
import os
import subprocess
from datetime import datetime, timezone

import loader

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


_write_log("loader", "ok", "Loader completed successfully")

subprocess.run(["dbt", "run", "--profiles-dir", "."], cwd=DBT_DIR, check=True)
_write_log("dbt_run", "ok", "dbt run completed successfully")

subprocess.run(["dbt", "test", "--profiles-dir", "."], cwd=DBT_DIR, check=True)
_write_log("dbt_test", "ok", "dbt test completed successfully")
