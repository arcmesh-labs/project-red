import duckdb

con = duckdb.connect("pipeline.duckdb")
con.execute("CREATE SCHEMA IF NOT EXISTS raw")
con.execute("""
    CREATE TABLE IF NOT EXISTS raw.data AS
    SELECT * FROM read_json_auto('input/data.json')
""")
con.close()
