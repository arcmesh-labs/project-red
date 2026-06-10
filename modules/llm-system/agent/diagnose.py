import json
import os
import sys

import anthropic

from agent.git_handler import open_pr
from agent.notify import send_notification
from agent.sandbox import run_sandbox_loop
from agent.tools import TOOLS, dispatch

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
LOG_FILE = os.path.join(_ROOT, "logs/pipeline.log")
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096
MAX_TOOL_CALLS = 10
SYSTEM_PROMPT = (
    "You are a dbt pipeline debugger. You have received a structured error log entry from a failed dbt run. "
    "There are two types of errors you may encounter:\n\n"
    "1. Model error — the error message references a specific .sql file. "
    "Your first action must be to read that specific file directly. "
    "Do not list directories. Go straight to the file.\n\n"
    "2. Compilation error or macro error — the error message does not reference a file path "
    "(e.g. 'No filter named X', 'Compilation Error', 'macro not found'). "
    "If the error message contains no file path, you must always start by reading the macro files "
    "in dbt/macros/ before doing anything else.\n\n"
    "In both cases: read the relevant file(s), identify the problem, and propose a concrete fix. "
    "Stop as soon as you have enough information."
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

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": initial_message}]

    print("[diagnose] starting tool-use loop")
    tool_call_count = 0
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            fix_text = ""
            for block in response.content:
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
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_call_count += 1
            print(f"[diagnose] tool: {block.name}")
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
