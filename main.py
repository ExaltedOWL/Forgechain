import hashlib

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from forgechain.block import ForgeBlock
from forgechain.chain import ForgeChain
from forgechain.gate import forge_gate
from forgechain.healer import trigger_healing_fork
from forgechain.interpreter import interpret_user_prompt
from forgechain.responder import generate_answer
from forgechain.store import get_store

load_dotenv()

app = FastAPI(title="ForgeChain Demo")


class ChatRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1)
    session_id: str | None = Field(
        default=None,
        description="Reuse from prior response for multi-turn; omit to start a new chain.",
    )


def _load_or_create_chain(session_id: str | None) -> tuple[str, ForgeChain]:
    store = get_store()
    if session_id:
        loaded = store.load_chain(session_id)
        if not loaded:
            raise HTTPException(status_code=404, detail="unknown session_id")
        key, blocks = loaded
        return session_id, ForgeChain(session_id, session_key=key, blocks=blocks)
    sid, key = store.create_session()
    return sid, ForgeChain(sid, session_key=key, blocks=[])


@app.post("/chat")
async def chat(req: ChatRequest):
    store = get_store()
    session_id, chain = _load_or_create_chain(req.session_id)
    initial_len = len(chain.blocks)

    try:
        # 1. User realm (this turn)
        prompt_hash = hashlib.sha256(req.user_prompt.encode()).hexdigest()
        genesis = ForgeBlock(
            realm="user",
            original_prompt_hash=prompt_hash,
            raw_prompt_preview=req.user_prompt[:280],
            parsed_intent={
                "stage": "user_realm",
                "original_prompt_hash": prompt_hash,
                "char_length": len(req.user_prompt),
            },
            interpreter_model="pending",
            interpreter_confidence=0.0,
            invariants=[],
        )
        chain.append(genesis)

        # 2. Interpreter realm
        parsed_intent, invs, interp_confidence, interp_model = await interpret_user_prompt(
            req.user_prompt, prompt_hash
        )
        interpreter_block = ForgeBlock(
            realm="interpreter",
            original_prompt_hash=prompt_hash,
            raw_prompt_preview="[redacted]",
            parsed_intent=parsed_intent,
            invariants=invs,
            interpreter_model=interp_model,
            interpreter_confidence=interp_confidence,
        )
        chain.append(interpreter_block)

        # 3. Forge Gate
        token, gate_reason = await forge_gate(chain)
        if not token:
            if gate_reason == "policy_veto":
                return {
                    "status": "refused",
                    "reason": "interpreter_policy",
                    "intent": chain.blocks[-1].parsed_intent,
                    "session_id": session_id,
                }
            if gate_reason == "verify_failed":
                return {
                    "status": "error",
                    "detail": "chain_verify_failed",
                    "session_id": session_id,
                }
            result = await trigger_healing_fork(chain, "low consensus")
            return {
                "status": "blocked",
                "healed_result": result,
                "session_id": session_id,
            }

        # 4. Executor — require a valid minted token before any answer / side effects
        if not token.is_valid():
            raise HTTPException(
                status_code=403,
                detail="ForgeToken invalid or expired before execution",
            )

        interp_block = chain.blocks[-1]
        # Intent for the model: drop duplicate invariants key if present (already on token.scope)
        intent_for_answer = {
            k: v for k, v in token.intent.items() if k != "invariants"
        }
        answer, responder_model = await generate_answer(
            req.user_prompt, intent_for_answer or dict(token.intent)
        )
        result_hash = hashlib.sha256(answer.encode()).hexdigest()
        executor_block = ForgeBlock(
            realm="executor",
            original_prompt_hash=prompt_hash,
            raw_prompt_preview="[redacted]",
            parsed_intent=dict(token.intent),
            invariants=list(interp_block.invariants),
            interpreter_model=responder_model,
            interpreter_confidence=1.0,
            execution_proof={
                "status": "success",
                "result_hash": result_hash,
                "answer_length": len(answer),
                "forge_token_id": token.token_id,
            },
        )
        chain.append(executor_block)

        return {
            "status": "executed",
            "intent": token.intent,
            "token_id": token.token_id,
            "answer": answer,
            "session_id": session_id,
        }
    finally:
        if len(chain.blocks) > initial_len:
            store.replace_blocks(session_id, chain.blocks)


@app.get("/session/{session_id}/replay")
async def replay_session(session_id: str):
    store = get_store()
    loaded = store.load_chain(session_id)
    if not loaded:
        raise HTTPException(status_code=404, detail="unknown session_id")
    session_key, blocks = loaded
    chain = ForgeChain(session_id, session_key=session_key, blocks=blocks)
    return {
        "session_id": session_id,
        "verify_chain": chain.verify_chain(),
        "block_count": len(blocks),
        "blocks": [b.model_dump(mode="json") for b in blocks],
    }
