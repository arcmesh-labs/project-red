import json
import sys

import anthropic

from agent.tools import TOOLS, dispatch

LOG_FILE = "logs/pipeline.log"
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096


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

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    print(block.text)
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
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


if __name__ == "__main__":
    run()
