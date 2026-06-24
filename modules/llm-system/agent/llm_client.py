import json
import os
from types import SimpleNamespace

import yaml

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))


def _load_config():
    with open(os.path.join(_ROOT, "config/llm.yml")) as f:
        return yaml.safe_load(f)


def _block(type_, **attrs):
    return SimpleNamespace(type=type_, **attrs)


class LLMClient:
    def __init__(self):
        cfg = _load_config()
        self.provider = cfg.get("provider", "anthropic")
        self.model = cfg.get("model", "claude-haiku-4-5")
        self.base_url = cfg.get("base_url") or ""
        self.max_tokens = 4096

    # ── tool format ───────────────────────────────────────────────────────────

    def _to_openai_tools(self, tools):
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def _to_google_schema(self, json_schema):
        import google.generativeai.protos as protos
        type_map = {
            "string": protos.Type.STRING,
            "integer": protos.Type.INTEGER,
            "number": protos.Type.NUMBER,
            "boolean": protos.Type.BOOLEAN,
            "array": protos.Type.ARRAY,
            "object": protos.Type.OBJECT,
        }
        stype = type_map.get(json_schema.get("type", "string"), protos.Type.STRING)
        props = {k: self._to_google_schema(v) for k, v in json_schema.get("properties", {}).items()}
        return protos.Schema(
            type_=stype,
            properties=props,
            required=json_schema.get("required", []),
            description=json_schema.get("description", ""),
        )

    def _to_google_tools(self, tools):
        import google.generativeai.protos as protos
        return protos.Tool(
            function_declarations=[
                protos.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=self._to_google_schema(t["input_schema"]),
                )
                for t in tools
            ]
        )

    # ── message format ────────────────────────────────────────────────────────

    def _block_to_dict(self, block):
        if isinstance(block, dict):
            return block
        d = {"type": getattr(block, "type", None)}
        if d["type"] == "text":
            d["text"] = getattr(block, "text", "")
        elif d["type"] == "tool_use":
            d.update({
                "id": getattr(block, "id", ""),
                "name": getattr(block, "name", ""),
                "input": getattr(block, "input", {}),
            })
        return d

    def _to_anthropic_messages(self, messages):
        result = []
        for msg in messages:
            content = msg["content"]
            if isinstance(content, list):
                content = [self._block_to_dict(b) for b in content]
            result.append({"role": msg["role"], "content": content})
        return result

    def _to_openai_messages(self, messages, system=None):
        result = []
        if system:
            result.append({"role": "system", "content": system})
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "user":
                if isinstance(content, str):
                    result.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                        for tr in content:
                            result.append({
                                "role": "tool",
                                "tool_call_id": tr["tool_use_id"],
                                "content": tr.get("content", ""),
                            })
                    else:
                        result.append({"role": "user", "content": str(content)})
            elif role == "assistant":
                if isinstance(content, str):
                    result.append({"role": "assistant", "content": content})
                elif isinstance(content, list):
                    def _get(b, key, default=None):
                        if isinstance(b, dict):
                            return b.get(key, default)
                        return getattr(b, key, default)

                    text = " ".join(
                        _get(b, "text", "")
                        for b in content
                        if _get(b, "type") == "text"
                    ) or None
                    tool_calls = [
                        {
                            "id": _get(b, "id"),
                            "type": "function",
                            "function": {
                                "name": _get(b, "name"),
                                "arguments": json.dumps(_get(b, "input", {})),
                            },
                        }
                        for b in content
                        if _get(b, "type") == "tool_use"
                    ]
                    oai_msg = {"role": "assistant", "content": text}
                    if tool_calls:
                        oai_msg["tool_calls"] = tool_calls
                    result.append(oai_msg)
        return result

    def _to_google_contents(self, messages):
        import google.generativeai.protos as protos
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            google_role = "user" if role == "user" else "model"
            parts = []
            if isinstance(content, str):
                parts.append(protos.Part(text=content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            # tool_use_id == function name for Google (see _google_chat_with_tools)
                            parts.append(protos.Part(
                                function_response=protos.FunctionResponse(
                                    name=block["tool_use_id"],
                                    response={"content": block.get("content", "")},
                                )
                            ))
                    else:
                        if block.type == "text":
                            parts.append(protos.Part(text=block.text))
                        elif block.type == "tool_use":
                            parts.append(protos.Part(
                                function_call=protos.FunctionCall(
                                    name=block.name,
                                    args=block.input,
                                )
                            ))
            contents.append({"role": google_role, "parts": parts})
        return contents

    # ── anthropic ─────────────────────────────────────────────────────────────

    def _anthropic_chat(self, messages, system):
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        return next((b.text for b in response.content if hasattr(b, "text")), "")

    def _anthropic_chat_with_tools(self, messages, tools, system):
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "tools": tools,
            "messages": self._to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        content = [
            _block("text", text=b.text) if b.type == "text"
            else _block("tool_use", id=b.id, name=b.name, input=b.input)
            for b in response.content
        ]
        return response.stop_reason, content

    # ── openai-compatible (openai, deepseek, mistral, ollama) ─────────────────

    def _openai_client(self):
        from openai import OpenAI
        p = self.provider
        if p == "ollama":
            base = self.base_url.rstrip("/") + "/v1" if self.base_url else "http://localhost:11434/v1"
            return OpenAI(api_key="ollama", base_url=base)
        if p == "deepseek":
            return OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com")
        if p == "mistral":
            return OpenAI(api_key=os.environ.get("MISTRAL_API_KEY"), base_url="https://api.mistral.ai/v1")
        return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def _openai_stop_reason(self, finish_reason):
        return {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}.get(
            finish_reason, finish_reason
        )

    def _openai_chat(self, messages, system):
        response = self._openai_client().chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages, system),
        )
        return response.choices[0].message.content or ""

    def _openai_chat_with_tools(self, messages, tools, system):
        response = self._openai_client().chat.completions.create(
            model=self.model,
            messages=self._to_openai_messages(messages, system),
            tools=self._to_openai_tools(tools),
        )
        choice = response.choices[0]
        msg = choice.message
        content = []
        if msg.content:
            content.append(_block("text", text=msg.content))
        for tc in msg.tool_calls or []:
            content.append(_block(
                "tool_use",
                id=tc.id,
                name=tc.function.name,
                input=json.loads(tc.function.arguments),
            ))
        return self._openai_stop_reason(choice.finish_reason), content

    # ── google ────────────────────────────────────────────────────────────────

    def _google_model(self, tools=None, system=None):
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        kwargs = {"model_name": self.model, "system_instruction": system or ""}
        if tools:
            kwargs["tools"] = [self._to_google_tools(tools)]
        return genai.GenerativeModel(**kwargs)

    def _google_chat(self, messages, system):
        model = self._google_model(system=system)
        response = model.generate_content(self._to_google_contents(messages))
        return response.text

    def _google_chat_with_tools(self, messages, tools, system):
        model = self._google_model(tools=tools, system=system)
        response = model.generate_content(self._to_google_contents(messages))
        content = []
        has_tool = False
        for part in response.parts:
            if getattr(part, "text", ""):
                content.append(_block("text", text=part.text))
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", ""):
                has_tool = True
                # Use function name as ID so tool_results can round-trip without extra state
                content.append(_block("tool_use", id=fc.name, name=fc.name, input=dict(fc.args)))
        return ("tool_use" if has_tool else "end_turn"), content

    # ── public interface ──────────────────────────────────────────────────────

    def chat(self, messages, system=None):
        if self.provider == "anthropic":
            return self._anthropic_chat(messages, system)
        if self.provider in ("openai", "deepseek", "mistral", "ollama"):
            return self._openai_chat(messages, system)
        if self.provider == "google":
            return self._google_chat(messages, system)
        raise ValueError(f"Unknown provider: {self.provider}")

    def chat_with_tools(self, messages, tools, system=None):
        if self.provider == "anthropic":
            return self._anthropic_chat_with_tools(messages, tools, system)
        if self.provider in ("openai", "deepseek", "mistral", "ollama"):
            return self._openai_chat_with_tools(messages, tools, system)
        if self.provider == "google":
            return self._google_chat_with_tools(messages, tools, system)
        raise ValueError(f"Unknown provider: {self.provider}")
