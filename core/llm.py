"""Pluggable LLM clients. The LLM NEVER sets or edits a score — it only writes text.

- GroqLLMClient: online. Model id from GROQ_MODEL, key from env or st.secrets; temperature 0.2;
  ONE retry; `complete_structured` expects a JSON object. A missing GROQ_MODEL or key
  HARD-FAILS with a clear message — no default is ever guessed.
- TemplateLLMClient: offline deterministic templates; the default (policy llm_enabled=false).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Protocol


class LLMClient(Protocol):
    offline: bool
    model_id: str

    def complete(self, prompt: str) -> str: ...

    def complete_structured(self, prompt: str) -> Dict[str, Any]: ...


def _secret(name: str) -> str | None:
    """Read a secret from the environment, falling back to st.secrets when Streamlit runs."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        secret = st.secrets.get(name)
        return str(secret) if secret else None
    except Exception:
        return None


def _parse_json(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found in LLM response")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON is not an object")
    return parsed


class GroqLLMClient:
    offline = False

    def __init__(self, temperature: float = 0.2) -> None:
        self.temperature = temperature
        self._client = None

    @property
    def model_id(self) -> str:
        model = _secret("GROQ_MODEL")
        if not model:
            raise RuntimeError(
                "set GROQ_MODEL in .env — no default is guessed (model ids change; "
                "online calls hard-fail without it)."
            )
        return model

    def _chat(self, prompt: str) -> str:
        api_key = _secret("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to .env (online calls need it; "
                "offline mode works with no key)."
            )
        from langchain_groq import ChatGroq  # lazy: offline never imports it

        if self._client is None:
            self._client = ChatGroq(api_key=api_key, model=self.model_id, temperature=self.temperature)
        return str(self._client.invoke(prompt).content)

    def complete(self, prompt: str) -> str:
        try:
            return self._chat(prompt)
        except RuntimeError:
            raise
        except Exception as first:
            try:  # exactly one retry
                return self._chat(prompt)
            except Exception as second:
                raise RuntimeError(f"Groq call failed after one retry: {second}") from first

    def complete_structured(self, prompt: str) -> Dict[str, Any]:
        return _parse_json(self.complete(prompt + "\nRespond with ONLY a single JSON object."))


class TemplateLLMClient:
    """Offline stand-in: deterministic, network-free. Agents fall back to their templates."""

    offline = True
    model_id = "offline-templates"

    def complete(self, prompt: str) -> str:
        first_line = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
        return f"[offline template response] {first_line}"

    def complete_structured(self, prompt: str) -> Dict[str, Any]:
        return {}  # no structured content offline; agents use their deterministic templates


def make_llm_client(offline: bool) -> LLMClient:
    return TemplateLLMClient() if offline else GroqLLMClient()
