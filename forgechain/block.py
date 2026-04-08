import hashlib
import secrets
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ForgeBlock(BaseModel):
    block_id: str = Field(default_factory=lambda: secrets.token_hex(8))
    previous_hash: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    realm: Literal["user", "interpreter", "verifier", "executor", "healer"]

    # Raw user input is NEVER exposed downstream
    original_prompt_hash: str
    raw_prompt_preview: str = Field(..., max_length=300)

    # ONLY this structured intent travels forward
    parsed_intent: dict
    intent_schema_version: str = "forge-v1"

    invariants: list[str] = Field(default_factory=list)
    interpreter_model: str
    interpreter_confidence: float = Field(ge=0.0, le=1.0)

    verifier_attestations: list[dict] = Field(default_factory=list)
    execution_proof: Optional[dict] = None

    signature: str = ""

    def compute_hash(self) -> str:
        data = self.model_dump_json(exclude={"signature", "verifier_attestations"})
        return hashlib.sha256(data.encode()).hexdigest()

    def sign(self, session_key: str):
        self.signature = hashlib.sha256(
            f"{self.compute_hash()}{session_key}".encode()
        ).hexdigest()
