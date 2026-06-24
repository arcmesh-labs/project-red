import json
import os
import sys

from agent.git_handler import open_pr
from agent.llm_client import LLMClient
from agent.notify import send_notification
from agent.sandbox import run_sandbox_loop
from agent.tools import TOOLS, dispatch

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
_DBT_ROOT = os.path.join(_ROOT, "modules/pipeline/dbt")
LOG_FILE = os.path.join(_ROOT, "logs/pipeline.log")
MAX_TOOL_CALLS = 10
SYSTEM_PROMPT = (
    f"You are a dbt pipeline debugger. The dbt project root is {_DBT_ROOT}/.\n"
    f"Relevant paths under the dbt root:\n"
    f"  - {_DBT_ROOT}/models/         — SQL model files\n"
    f"  - {_DBT_ROOT}/macros/         — Jinja macro files\n"
    f"  - {_DBT_ROOT}/dbt_project.yml — project schema and materialization config\n"
    f"  - {_DBT_ROOT}/profiles.yml    — connection and target schema config\n\n"
    "Step 1 — Parse the error log. Before calling any tool, extract from the dbt output:\n"
    "  - The exact file path (e.g. models/bronze/bronze_data.sql)\n"
    "  - The line number if present\n"
    "  - The error message\n"
    f"  A relative path like models/bronze/bronze_data.sql resolves to {_DBT_ROOT}/models/bronze/bronze_data.sql.\n\n"
    f"Step 2 — Read project config. Your first two tool calls must be read_file on "
    f"{_DBT_ROOT}/dbt_project.yml and {_DBT_ROOT}/profiles.yml to understand schemas and "
    "materialization before reading any model or macro files.\n\n"
    "Step 3 — Read the error file directly. If the error references a file path, call read_file "
    "on the full resolved path. Do not call list_directory.\n\n"
    "Step 4 — Use list_directory only as a fallback. If the error contains no file path "
    "(e.g. 'No filter named X', 'Compilation Error', 'macro not found'), use list_directory "
    f"on {_DBT_ROOT}/macros/ to locate relevant macro files.\n\n"
    "Step 5 — Propose a minimal, targeted fix. Only address the file(s) mentioned in the error. "
    "Do not modify any file not directly implicated by the error message.\n\n"
    "Stop as soon as you have read the relevant file(s) and can state a concrete fix."
)


def find_last_error() -> dict:
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Log file not found: {LOG_FILE}")
        sys.exit(1)

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("status") == "error":
            return entry

    print("No error entries found in log.")
    sys.exit(0)


def run():
    error_entry = find_last_error()
    initial_message = (
        "Pipeline error detected. Investigate the codebase to understand the cause "
        "and suggest a concrete fix.\n\n"
        f"{json.dumps(error_entry, indent=2)}"
    )

    llm = LLMClient()
    messages = [{"role": "user", "content": initial_message}]

    print("[diagnose] starting tool-use loop")
    tool_call_count = 0
    while True:
        stop_reason, content = llm.chat_with_tools(messages, TOOLS, system=SYSTEM_PROMPT)

        messages.append({"role": "assistant", "content": content})

        if stop_reason == "end_turn":
            fix_text = ""
            for block in content:
                if hasattr(block, "text"):
                    fix_text += block.text
                    print(block.text)
            print("[diagnose] handing off to sandbox")
            result = run_sandbox_loop(fix_text, error_entry, messages)
            print(result)
            if result["status"] == "success":
                pr_url = open_pr(result, error_entry, messages)
                print(f"[diagnose] PR opened: {pr_url}")
                send_notification(result, pr_url)
            else:
                send_notification(result)
            break

        tool_results = []
        for block in content:
            if block.type != "tool_use":
                continue
            tool_call_count += 1
            print(f"[diagnose] tool: {block.name} path={block.input}")
            try:
                output = dispatch(block.name, block.input)
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

        messages.append({"role": "user", "content": tool_results})

        if tool_call_count >= MAX_TOOL_CALLS:
            print(f"[diagnose] reached max tool calls ({MAX_TOOL_CALLS}), stopping")
            break


if __name__ == "__main__":
    run()
