import asyncio
import copy

from .chain import ForgeChain


async def trigger_healing_fork(chain: ForgeChain, anomaly_reason: str):
    print(f"🚨 ANOMALY DETECTED: {anomaly_reason} → Forking chain {chain.session_id}")

    # Create clean fork up to last good block
    fork = copy.deepcopy(chain)
    fork.blocks = fork.blocks[:-1]  # drop suspicious block

    # 3 mutation strategies
    mutations = [
        {"action": "sanitize", "intent": {**chain.get_latest_intent(), "reason": "cleaned"}},
        {"action": "rephrase", "intent": chain.get_latest_intent()},
        {
            "action": "test_attack",
            "intent": {**chain.get_latest_intent(), "action": "safe_read"},
        },
    ]

    # Replay in parallel (simplified)
    results = await asyncio.gather(*[simulate_replay(fork, m) for m in mutations])
    cleanest = max(results, key=lambda r: r["safety_score"])

    if cleanest["safety_score"] > 0.9:
        print("✅ Clean fork promoted")
        # In real app: replace original chain result with cleanest
        return cleanest["result"]
    else:
        print("⛔ Full quarantine")
        return {"status": "quarantined", "reason": anomaly_reason}


async def simulate_replay(fork: ForgeChain, mutation: dict):
    # Placeholder — in production call executor with mutated intent
    await asyncio.sleep(0.1)
    return {
        "safety_score": 0.95 if mutation["action"] != "test_attack" else 0.3,
        "result": "success",
    }
