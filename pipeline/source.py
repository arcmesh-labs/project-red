import pandas as pd
from datetime import datetime, timezone


def fetch() -> dict:
    df = pd.read_json("input/data.json")
    return {
        "source": "data.json",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "payload": df,
    }
