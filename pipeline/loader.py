import yaml
import duckdb
from adapters.json_adapter import JsonAdapter

with open("config/duckdb.yml") as f:
    db_cfg = yaml.safe_load(f)

with open("config/input.yml") as f:
    input_cfg = yaml.safe_load(f)

db_path = db_cfg["database"]
raw_schema = db_cfg["schemas"]["raw"]

adapters = {"json": JsonAdapter}
adapter = adapters[input_cfg["adapter"]](input_cfg["path"])
df = adapter.fetch()

con = duckdb.connect(db_path)
con.execute(f"CREATE SCHEMA IF NOT EXISTS {raw_schema}")
con.register("input_df", df)
con.execute(f"CREATE TABLE IF NOT EXISTS {raw_schema}.data AS SELECT * FROM input_df")
con.close()
