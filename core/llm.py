"""Pluggable LLM clients. The LLM never sets or edits a score.

- GroqLLMClient: online; validates env AT CALL TIME; no guessed default — a missing GROQ_MODEL
  hard-fails with a clear "set GROQ_MODEL" message.
- TemplateLLMClient: offline; deterministic templates; works with no key.
"""

from __future__ import annotations

import os
from typing import Protocol


class LLMClient(Protocol):
    offline: bool

    def complete(self, prompt: str) -> str: ...


class GroqLLMClient:
    offline = False

    def complete(self, prompt: str) -> str:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to .env (online calls need it; --offline works without a key)."
            )
        model = os.environ.get("GROQ_MODEL")
        if not model:
            raise RuntimeError(
                "set GROQ_MODEL in .env — no default is guessed (model ids change; use a verified id)."
            )
        from langchain_groq import ChatGroq  # lazy import: offline mode never needs it

        response = ChatGroq(api_key=api_key, model=model).invoke(prompt)
        return str(response.content)


class TemplateLLMClient:
    """Offline stand-in: deterministic, network-free, records that it is a template."""

    offline = True

    def complete(self, prompt: str) -> str:
        first_line = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
        return f"[offline template response] {first_line}"


def make_llm_client(offline: bool) -> LLMClient:
    return TemplateLLMClient() if offline else GroqLLMClient()
