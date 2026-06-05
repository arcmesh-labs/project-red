from adapters.base import BaseAdapter
import pandas as pd


class JsonAdapter(BaseAdapter):
    def __init__(self, path: str):
        self.path = path

    def fetch(self) -> pd.DataFrame:
        return pd.read_json(self.path)
