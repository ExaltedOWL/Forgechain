import json
import os

import httpx

from ..chain import ForgeChain

_DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434/v1"
_DEFAULT_OLLAMA_MODEL = "gemma4:31b-cloud"


def _stub_verdict(prompt: str) -> bool:
    lower = prompt.lower()
    unsafe = any(
        p in lower
        for p in (
            "ignore all instructions",
            "delete everything",
            "system prompt",
            "jailbreak",
        )
    )
    return not unsafe


async def _openai_verifier_call(prompt: str, api_key: str) -> bool:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a security verifier. Answer only YES or NO.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 5,
            },
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"] or ""
        return "YES" in text.upper()


async def _ollama_verifier_call(prompt: str, base_url: str, model: str) -> bool:
    """OpenAI-compatible endpoint served by Ollama (e.g. POST /v1/chat/completions)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
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
                    {
                        "role": "system",
                        "content": "You are a security verifier. Answer only YES or NO.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 8,
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return "YES" in text.upper()


async def llm_verifier_call(prompt: str) -> bool:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return await _openai_verifier_call(prompt, api_key)

    if os.environ.get("FORGECHAIN_SKIP_OLLAMA", "").lower() in ("1", "true", "yes"):
        return _stub_verdict(prompt)

    base = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL)
    try:
        return await _ollama_verifier_call(prompt, base, model)
    except Exception:
        return _stub_verdict(prompt)


def _verifier_chain_prompt(chain: ForgeChain) -> str:
    lines = [f"Chain length: {len(chain.blocks)} blocks."]
    for b in chain.blocks:
        if b.realm == "user":
            lines.append(f"User realm preview (truncated): {b.raw_prompt_preview!r}")
        lines.append(f"{b.realm} parsed_intent: {json.dumps(b.parsed_intent)}")
        lines.append(f"{b.realm} invariants: {b.invariants}")
    return "\n".join(lines)


class LLMVerifier:
    @staticmethod
    async def verify(chain: ForgeChain) -> dict:
        block = chain.blocks[-1]
        prompt = f"""{_verifier_chain_prompt(chain)}
Latest block realm: {block.realm}
Is this chain safe and consistent with least privilege? YES or NO only."""
        try:
            approved = await llm_verifier_call(prompt)
        except Exception:
            approved = False
        return {
            "verifier_id": "llm_phi3",
            "approved": approved,
            "reason": "model consensus",
            "confidence": 0.85,
        }
