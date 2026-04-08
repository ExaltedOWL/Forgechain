"""
Executor-side answer generation: runs only after a ForgeToken is minted (gate passed).
Sends the user question to an LLM with approved intent as context.
"""

from __future__ import annotations

import json
import os
import re

import httpx

_DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434/v1"


def _responder_ollama_model() -> str:
    return os.environ.get("RESPONDER_OLLAMA_MODEL") or os.environ.get(
        "OLLAMA_MODEL", "gemma4:31b-cloud"
    )


def _openai_answer_model() -> str:
    return os.environ.get("RESPONDER_OPENAI_MODEL", "gpt-4o-mini")


RESPONDER_SYSTEM = """You are the ForgeChain executor assistant. The user's request already passed safety review.
Answer clearly and concisely. For arithmetic, give the numeric result. No preambles like "The answer is" unless helpful."""


async def _openai_answer(user_prompt: str, intent: dict, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": _openai_answer_model(),
                "messages": [
                    {"role": "system", "content": RESPONDER_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Approved intent (JSON):\n{json.dumps(intent, indent=2)}\n\nUser question:\n{user_prompt}",
                    },
                ],
                "max_tokens": 1024,
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        return (
            (resp.json().get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )


async def _ollama_answer(user_prompt: str, intent: dict, base: str, model: str) -> str:
    url = f"{base.rstrip('/')}/chat/completions"
    timeout = httpx.Timeout(
        connect=5.0,
        read=float(os.environ.get("OLLAMA_TIMEOUT", "120")),
        write=30.0,
        pool=5.0,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": RESPONDER_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Approved intent (JSON):\n{json.dumps(intent, indent=2)}\n\nUser question:\n{user_prompt}",
                    },
                ],
                "max_tokens": 1024,
                "temperature": 0.2,
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )


def _stub_answer(user_prompt: str) -> str:
    m = re.match(r"^\s*(\d+)\s*\+\s*(\d+)\s*\??\s*$", user_prompt.strip())
    if m:
        return str(int(m.group(1)) + int(m.group(2)))
    return (
        "[Responder stub] Set Ollama/OpenAI (unset FORGECHAIN_SKIP_OLLAMA) for full answers. "
        "Try a question like '1+1' for a local arithmetic demo."
    )


async def generate_answer(user_prompt: str, intent: dict) -> tuple[str, str]:
    """
    Returns (answer_text, model_label_for_provenance).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        text = await _openai_answer(user_prompt, intent, api_key)
        return text or "(empty response)", _openai_answer_model()

    if os.environ.get("FORGECHAIN_SKIP_OLLAMA", "").lower() in ("1", "true", "yes"):
        return _stub_answer(user_prompt), "responder_stub"

    base = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE).rstrip("/")
    model = _responder_ollama_model()
    try:
        text = await _ollama_answer(user_prompt, intent, base, model)
        return (text or "(empty response)", model)
    except Exception:
        return _stub_answer(user_prompt), "responder_stub"
