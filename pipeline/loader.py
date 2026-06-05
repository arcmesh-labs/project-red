import yaml
import duckdb
from source import fetch

with open("config/duckdb.yml") as f:
    db_cfg = yaml.safe_load(f)

db_path = db_cfg["database"]
raw_schema = db_cfg["schemas"]["raw"]

result = fetch()
df = result["payload"]
df["_source"] = result["source"]
df["_extracted_at"] = result["extracted_at"]

con = duckdb.connect(db_path)
con.execute(f"CREATE SCHEMA IF NOT EXISTS {raw_schema}")
con.register("input_df", df)
con.execute(f"DROP TABLE IF EXISTS {raw_schema}.data")
con.execute(f"CREATE TABLE {raw_schema}.data AS SELECT * FROM input_df")
con.close()
