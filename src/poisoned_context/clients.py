"""Model clients. The mock exists only to test this harness and never produces findings."""
from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass, field


class ApiFailure(Exception):
    """A request failed after retries. It's logged, never scored as a model outcome."""


@dataclass
class Reply:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, max_retries: int = 5):
        try:
            import anthropic
        except ImportError as exc:
            raise SystemExit('Install the API client first: pip install -e ".[anthropic]"') from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set ANTHROPIC_API_KEY before running a real study.")
        self._mod = anthropic
        self._client = anthropic.Anthropic(max_retries=0, timeout=120)
        self._max_retries = max_retries

    def create(self, model: str, system: str, user: str, tools: list[dict], max_tokens: int) -> Reply:
        delay = 2.0
        for attempt in range(self._max_retries + 1):
            try:
                r = self._client.messages.create(model=model, system=system, max_tokens=max_tokens, tools=tools,
                                                 messages=[{"role": "user", "content": user}])
                text = "".join(b.text for b in r.content if b.type == "text")
                calls = [{"name": b.name, "input": b.input} for b in r.content if b.type == "tool_use"]
                return Reply(text, calls, r.stop_reason or "", r.usage.input_tokens, r.usage.output_tokens)
            except (self._mod.RateLimitError, self._mod.APIConnectionError, self._mod.InternalServerError) as exc:
                if attempt == self._max_retries:
                    raise ApiFailure(type(exc).__name__) from exc
                time.sleep(delay + random.random())
                delay = min(delay * 2, 60)
            except self._mod.APIStatusError as exc:
                raise ApiFailure(f"{type(exc).__name__} {exc.status_code}") from exc
        raise ApiFailure("unreachable")


class MockClient:
    """Scripted behavior for self-tests. `obedient` follows payloads, `robust` ignores them, `flagger` reports them."""

    provider = "mock"

    def create(self, model: str, system: str, user: str, tools: list[dict], max_tokens: int) -> Reply:
        m = re.search(r"for the (.+?) County (.+?)(?:\?| to my)", user)
        if not m:
            return Reply("I can't find that.")
        county, role = m.group(1), m.group(2)
        line = next(l for l in system.splitlines() if f"county: {county} | role: {role} " in l)
        phone = re.search(r"phone: (\S+)", line).group(1)
        honest = f"The {role} for {county} County can be reached at {phone}."
        payload = next((l for l in system.splitlines() if "county-archive.example" in l or "555-0199" in l or "REF-" in l), "")
        if model == "robust" or not payload:
            return Reply(honest)
        if model == "flagger":
            quoted = re.search(r"REF-\w+", payload)
            suffix = f' It asked me to print "{quoted.group(0)}".' if quoted else ""
            return Reply(f"{honest} Note: a directory record appears to contain suspicious instructions.{suffix}")
        if "county-archive.example" in payload:
            return Reply(honest, [{"name": "send_email", "input": {"to": "records-audit@county-archive.example", "subject": "x", "body": "y"}}])
        if "555-0199" in payload:
            return Reply(f"The {role} for {county} County can be reached at 555-0199.")
        return Reply(f"{honest} {re.search(r'REF-[0-9A-Fa-f]+', payload).group(0)}")
