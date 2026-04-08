from ..chain import ForgeChain


class RuleVerifier:
    @staticmethod
    async def verify(chain: ForgeChain) -> dict:
        block = chain.blocks[-1]
        approved = all(
            inv in block.invariants for inv in ["read_only", "user_owns_resource"]
        ) or block.interpreter_confidence > 0.9
        return {
            "verifier_id": "rule_v1",
            "approved": approved,
            "reason": "invariants satisfied" if approved else "violates policy",
            "confidence": 1.0,
        }
