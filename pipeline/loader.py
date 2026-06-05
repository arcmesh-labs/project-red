import yaml
import duckdb

with open("config/duckdb.yml") as f:
    cfg = yaml.safe_load(f)

db_path = cfg["database"]
raw_schema = cfg["schemas"]["raw"]

con = duckdb.connect(db_path)
con.execute(f"CREATE SCHEMA IF NOT EXISTS {raw_schema}")
con.execute(f"""
    CREATE TABLE IF NOT EXISTS {raw_schema}.data AS
    SELECT * FROM read_json_auto('input/data.json')
""")
con.close()
