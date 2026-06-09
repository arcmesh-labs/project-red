import os
import shutil
import subprocess

import anthropic
import duckdb
import yaml

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096


def _sandbox_tools():
    return [
        {
            "name": "list_directory",
            "description": "List files in a directory.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "read_file",
            "description": "Read a file's contents.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to a file. Only permitted within the sandbox directory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
        },
    ]


def _dispatch_sandbox(name, input_data, sandbox_dir):
    if name == "list_directory":
        return "\n".join(sorted(os.listdir(input_data["path"])))
    if name == "read_file":
        with open(input_data["path"]) as f:
            return f.read()
    if name == "write_file":
        path = input_data["path"]
        if not os.path.abspath(path).startswith(os.path.abspath(sandbox_dir)):
            raise ValueError(f"Write access is restricted to sandbox: {sandbox_dir}")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(input_data["content"])
        return f"Written: {path}"
    raise ValueError(f"Unknown tool: {name}")


def _agent_loop(client, history, tools, dispatch_fn):
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=tools,
            messages=history,
        )
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                output = dispatch_fn(block.name, block.input)
                is_error = False
            except Exception as e:
                output = str(e)
                is_error = True
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        history.append({"role": "user", "content": tool_results})


def _setup_sandbox(sandbox_dir, prod_db_path):
    shutil.copytree(
        "dbt",
        os.path.join(sandbox_dir, "dbt"),
        ignore=shutil.ignore_patterns("target", "logs", ".user.yml"),
    )

    sandbox_db_path = os.path.abspath(os.path.join(sandbox_dir, "sandbox.duckdb"))
    profiles_path = os.path.join(sandbox_dir, "dbt", "profiles.yml")
    with open(profiles_path) as f:
        profiles = yaml.safe_load(f)
    for profile_data in profiles.values():
        for output_data in profile_data.get("outputs", {}).values():
            if "path" in output_data:
                output_data["path"] = sandbox_db_path
    with open(profiles_path, "w") as f:
        yaml.dump(profiles, f)

    prod_con = duckdb.connect(prod_db_path, read_only=True)
    sandbox_con = duckdb.connect(sandbox_db_path)
    try:
        tables_df = prod_con.execute("SHOW ALL TABLES").df()
        for _, row in tables_df.iterrows():
            schema_name = row["schema"]
            table_name = row["name"]
            df = prod_con.execute(
                f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT 100'
            ).df()
            sandbox_con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
            sandbox_con.register("_tmp", df)
            sandbox_con.execute(
                f'CREATE TABLE "{schema_name}"."{table_name}" AS SELECT * FROM _tmp'
            )
    finally:
        prod_con.close()
        sandbox_con.close()


def _apply_fix(client, fix_suggestion, sandbox_dir, history):
    history.append({
        "role": "user",
        "content": (
            f"Apply the fix to the dbt models in {sandbox_dir}/dbt/. "
            f"Use write_file to write the corrected files.\n\n{fix_suggestion}"
        ),
    })
    _agent_loop(
        client,
        history,
        _sandbox_tools(),
        lambda name, inp: _dispatch_sandbox(name, inp, sandbox_dir),
    )


def _run_dbt(sandbox_dir):
    result = subprocess.run(
        ["dbt", "run", "--profiles-dir", "."],
        cwd=os.path.join(sandbox_dir, "dbt"),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout or result.stderr


def _get_new_fix(client, history):
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=history,
    )
    history.append({"role": "assistant", "content": response.content})
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""


def run_sandbox_loop(fix_suggestion, error_entry, conversation_history):
    with open("config/duckdb.yml") as f:
        db_cfg = yaml.safe_load(f)
    prod_db_path = db_cfg["database"]

    client = anthropic.Anthropic()
    history = list(conversation_history)
    fix_to_apply = fix_suggestion
    last_error = ""
    sandbox_base = "sandbox"

    print("[sandbox] starting loop, max 5 attempts")
    try:
        for attempt in range(1, 6):
            print(f"[sandbox] attempt {attempt}/5")
            sandbox_dir = os.path.join(sandbox_base, f"attempt_{attempt}")
            _setup_sandbox(sandbox_dir, prod_db_path)
            print("[sandbox] setup complete")
            _apply_fix(client, fix_to_apply, sandbox_dir, history)
            print("[sandbox] fix applied")
            success, output = _run_dbt(sandbox_dir)

            if success:
                print("[sandbox] dbt green ✓")
                return {"status": "success", "attempt": attempt, "fix": fix_to_apply}

            print("[sandbox] dbt red — getting new fix")
            last_error = output
            history.append({
                "role": "user",
                "content": (
                    f"dbt run failed in sandbox attempt {attempt}:\n{last_error}\n"
                    "Propose a new fix."
                ),
            })
            fix_to_apply = _get_new_fix(client, history)

        return {"status": "failed", "attempts": 5, "last_error": last_error}
    finally:
        print("[sandbox] cleaning up sandbox/")
        shutil.rmtree(sandbox_base, ignore_errors=True)
