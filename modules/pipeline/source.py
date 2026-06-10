import os
from datetime import datetime, timezone

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))


def fetch() -> dict:
    df = pd.read_json(os.path.join(_HERE, "input/data.json"))
    return {
        "source": "data.json",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "payload": df,
    }
