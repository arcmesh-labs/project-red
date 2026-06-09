import os

import duckdb
import yaml

TOOLS = [
    {
        "name": "list_directory",
        "description": "List files and directories at the given path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "query_duckdb",
        "description": "Run a read-only SELECT query against the pipeline DuckDB database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT statement to execute"},
            },
            "required": ["sql"],
        },
    },
]


def _list_directory(path: str) -> str:
    entries = os.listdir(path)
    return "\n".join(sorted(entries))


def _read_file(path: str) -> str:
    with open(path) as f:
        return f.read()


def _query_duckdb(sql: str) -> str:
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT statements are allowed.")
    with open("config/duckdb.yml") as f:
        db_cfg = yaml.safe_load(f)
    con = duckdb.connect(db_cfg["database"], read_only=True)
    try:
        result = con.execute(sql).df()
    finally:
        con.close()
    return result.to_string(index=False)


def dispatch(name: str, input_data: dict) -> str:
    if name == "list_directory":
        return _list_directory(input_data["path"])
    if name == "read_file":
        return _read_file(input_data["path"])
    if name == "query_duckdb":
        return _query_duckdb(input_data["sql"])
    raise ValueError(f"Unknown tool: {name}")
