import secrets
import time

from pydantic import BaseModel


class ForgeToken(BaseModel):
    token_id: str
    intent: dict
    expiry: int  # unix timestamp
    scope: list[str]  # e.g. ["read_only", "user_owned"]

    @classmethod
    def mint(cls, intent: dict, expiry_seconds: int = 60):
        return cls(
            token_id=secrets.token_hex(16),
            intent=intent,
            expiry=int(time.time()) + expiry_seconds,
            scope=intent.get("invariants", []),
        )

    def is_valid(self) -> bool:
        return time.time() < self.expiry
