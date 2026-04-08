# ForgeChain

Immutable block provenance, a **Forge Gate** (2/3 verifier consensus), short-lived **ForgeTokens**, and a **self-healing fork** hook — MVP skeleton using the standard library plus **Pydantic**, **HTTPX**, and **FastAPI**.

## Quick start

Use **Python 3.11–3.13** for the smoothest install, or **3.14** with a recent Pydantic (resolved by `pydantic>=2.10,<3` in `requirements.txt`).

```bash
cd forgechain
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
# Fish shell: source .venv/bin/activate.fish
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

**LLM verifier backends** (see `.env.example`):

1. If `OPENAI_API_KEY` is set → OpenAI `gpt-4o-mini`.
2. Else → **local Ollama** at `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434/v1`) with `OLLAMA_MODEL` (default `gemma4:31b-cloud`). Ensure Ollama is running and the model is available.
3. If Ollama is unreachable or you set `FORGECHAIN_SKIP_OLLAMA=1` → conservative **offline stub** (keyword heuristic).

## API: `POST /chat`

- Send **JSON** with header **`Content-Type: application/json`** (required). Plain `-d '{...}'` without that header will **not** parse as JSON and FastAPI will return **422**.
- Body: **`user_prompt`** (string, required); **`session_id`** (string, optional — omit to start a new chain, reuse from the last response for multi-turn).

### Example curls

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_prompt": "What is 1+1?"}'

curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_prompt": "And 2+2?", "session_id": "<paste_session_id>"}'
```

**Forensic replay:**

```bash
curl -s "http://127.0.0.1:8000/session/<session_id>/replay"
```

## Forge Gate: outcomes and token minting

Each turn appends **user** → **interpreter** blocks, then runs the gate. A **ForgeToken** is minted only if the gate allows it; the **executor** (responder) runs only after a **valid** token.

| `status` | Token minted? | Executor / `answer`? | When |
|----------|---------------|----------------------|------|
| **`executed`** | Yes | Yes | Chain verifies, no policy veto, **≥ 2 of 3** verifiers approve. |
| **`refused`** | No | No | **Policy veto**: interpreter `action` is **`reject`** or **`safety_review`** (hard stop; verifiers are not even run for minting). |
| **`blocked`** | No | No | **Low consensus**: chain verifies, not vetoed, but **&lt; 2 of 3** verifiers approve → **`trigger_healing_fork`** runs (see below). |
| **`error`** | No | No | **`verify_chain`** failed at the gate (integrity / signature link issue). |

Response always includes **`session_id`** when the handler finishes (new or existing session). **`refused`** includes **`reason: interpreter_policy`** and the interpreter **`intent`**.

### Policy veto vs healing fork (important)

- **Not minted** by itself does **not** decide whether the healer runs. The **reason** matters:
  - **`refused` / policy veto** — Interpreter already classified the turn as non-executable. There is **nothing to “heal”** into a safe execution path here; the API **does not** call the fork/healer.
  - **`blocked` / low consensus** — The interpreter allowed verification, but verifiers **disagreed**. That is treated as **ambiguous**, so the code **does** call **`trigger_healing_fork`** (currently a **placeholder**: fake safety scores, not a real re-run of interpreter + gate + executor).

So: **policy veto → no fork. Low consensus → fork hook (stub).**

### Verifier weights (MVP behavior)

The gate runs **three** checks: **rule** (pure Python) + **two LLM** verifiers. **Consensus is 2/3 approvals** counting all three.

**Finding:** The **rule** verifier can vote **no** (e.g. requires both `read_only` and `user_owns_resource`, or high interpreter confidence) while **both LLMs** vote **yes** — the token still **mints** because two approvals are enough. If you want policy to **veto** unless rules pass, that requires a **gate rule change** (e.g. rule must approve **and** 2 LLM, or rule holds a veto slot).

## Interpreter and executor (two different calls)

- **Interpreter** (`interpreter.py`) produces structured **`parsed_intent`** + **`invariants`**. Model: **`INTERPRETER_OLLAMA_MODEL`** (default **`kimi-k2.5:cloud`**) or OpenAI when configured. Falls back to **`interpreter_stub`** when `FORGECHAIN_SKIP_OLLAMA=1` or the call/parse fails.

**Finding:** You can see **`interpreter_model: interpreter_stub`** on replay while the **executor** still shows **`gemma4:31b-cloud`** — stub interpreter does not disable the **responder**; those are separate backends.

- **Executor / responder** (`responder.py`) runs **only after** a minted token. Model: **`RESPONDER_OLLAMA_MODEL`** or **`OLLAMA_MODEL`**, etc. With skip/stub, only trivial patterns like `1+1` get a local numeric answer.

## Sessions (SQLite)

- **`FORGECHAIN_DB`**: SQLite path (default **`forgechain.db`** in the process working directory). Listed in **`.gitignore`**.
- **New session**: omit **`session_id`**; response includes a new id. **Continue**: send the same **`session_id`**; new blocks append to the same chain and **`session_key`**.
- **`GET /session/{session_id}/replay`**: **`verify_chain`**, **`block_count`**, full **`blocks`** (audit / forensic replay).
- **Executor block** **`execution_proof`** includes **`result_hash`**, **`answer_length`**, **`forge_token_id`**.
- **Unknown `session_id`**: **404**.

**Finding:** A **refused** or **blocked** turn still **persists** the **user** + **interpreter** blocks for that turn (no executor block). Replay shows the full history including failed policy turns.

## Layout

| Path | Role |
|------|------|
| `forgechain/block.py` | `ForgeBlock` + signing |
| `forgechain/chain.py` | `ForgeChain` + verification |
| `forgechain/gate.py` | Forge Gate (veto + consensus + mint) |
| `forgechain/token.py` | `ForgeToken` (short-lived privilege) |
| `forgechain/interpreter.py` | Interpreter realm (LLM → JSON intent) |
| `forgechain/responder.py` | Post-gate answer (executor LLM) |
| `forgechain/verifiers/` | Rule + LLM verifiers |
| `forgechain/healer.py` | Fork/heal hook (placeholder replay) |
| `forgechain/store.py` | SQLite session + block persistence |
| `main.py` | FastAPI `/chat` + `/session/.../replay` |

## Design notes and known MVP limits

1. **Healer** — `healer.py` does **not** re-run interpreter, gate, or executor on a real fork; it simulates scores. Full “immune system” replay is future work.

2. **Genesis block** — `verify_chain` validates links and signatures from **block index 1** onward; the first block’s signature is not checked by that loop (documented limitation).

3. **Injection regression fixed** — Earlier, **`safety_review`** could still receive a token if **two LLM verifiers** said yes. **Policy veto** (`reject` / `safety_review`) now **prevents minting and execution** regardless of LLM votes.

4. **Separate sessions** — Omitting **`session_id`** on an attack creates a **new** chain; replay an older **`session_id`** to see a previous conversation unchanged.

5. **JSON errors** — Typos in the JSON body (e.g. trailing `}'` or extra characters) produce **`json_invalid`** / **422**, not a ForgeChain `status`.

## Next steps

1. Multi-tenant / tenant-scoped DB and keys.
2. Test suite with injection fixtures.
3. Stricter gate (e.g. rule veto or 3/5 verifiers).
4. Real fork replay (re-run interpreter + gate + executor in sandbox).
5. LangGraph (or Celery/Redis) for async verifiers at scale.

### Example: two-turn chat

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" \
  -d '{"user_prompt": "Remember the code word is banana"}'

curl -s -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" \
  -d '{"user_prompt": "What was the code word?", "session_id": "<paste_session_id>"}'

curl -s "http://127.0.0.1:8000/session/<paste_session_id>/replay"
```
