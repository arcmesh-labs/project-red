from abc import ABC, abstractmethod
import pandas as pd


class BaseAdapter(ABC):
    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        pass
