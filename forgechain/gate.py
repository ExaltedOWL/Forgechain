import asyncio

from .chain import ForgeChain
from .token import ForgeToken
from .verifiers.llm_verifier import LLMVerifier
from .verifiers.rule_verifier import RuleVerifier

# Interpreter classified as non-executable: never mint a token, skip LLM verifier spend.
POLICY_VETO_ACTIONS = frozenset({"reject", "safety_review"})


async def forge_gate(chain: ForgeChain) -> tuple[ForgeToken | None, str | None]:
    """
    Returns (token, reason_if_no_token).
    reason_if_no_token: "verify_failed" | "policy_veto" | "low_consensus" | None when token minted.
    """
    if not chain.verify_chain():
        return None, "verify_failed"

    latest = chain.blocks[-1]
    act = latest.parsed_intent.get("action")
    if act in POLICY_VETO_ACTIONS:
        return None, "reject"

    # Run 3 verifiers in parallel
    results = await asyncio.gather(
        RuleVerifier.verify(chain),
        LLMVerifier.verify(chain),
        LLMVerifier.verify(chain),  # second LLM instance (different temp or model)
    )

    approvals = sum(1 for r in results if r["approved"])
    if approvals >= 2:  # 2/3 consensus
        intent_with_scope = {
            **latest.parsed_intent,
            "invariants": list(latest.invariants),
        }
        token = ForgeToken.mint(intent_with_scope)
        # Attach attestations
        latest.verifier_attestations.extend(results)
        return token, None
    return None, "low_consensus"
