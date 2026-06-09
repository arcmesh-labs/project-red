import json
import sys

import anthropic

from agent.git_handler import open_pr
from agent.sandbox import run_sandbox_loop
from agent.tools import TOOLS, dispatch

LOG_FILE = "logs/pipeline.log"
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096
MAX_TOOL_CALLS = 10
SYSTEM_PROMPT = (
    "You are a dbt pipeline debugger. You have received an error message from a failed dbt run. "
    "Your job is to identify the root cause and propose a fix. "
    "Focus only on files directly relevant to the error. Do not explore the entire codebase. "
    "Stop as soon as you have enough information to propose a fix."
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
