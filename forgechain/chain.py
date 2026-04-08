import hashlib
import secrets
from typing import List

from .block import ForgeBlock


class ForgeChain:
    def __init__(
        self,
        session_id: str,
        session_key: str | None = None,
        blocks: List[ForgeBlock] | None = None,
    ):
        self.session_id = session_id
        self.blocks: List[ForgeBlock] = list(blocks) if blocks is not None else []
        self.session_key = session_key or secrets.token_hex(32)

    def append(self, block: ForgeBlock):
        if self.blocks:
            block.previous_hash = self.blocks[-1].compute_hash()
        block.sign(self.session_key)
        self.blocks.append(block)

    def verify_chain(self) -> bool:
        for i in range(1, len(self.blocks)):
            if self.blocks[i].previous_hash != self.blocks[i - 1].compute_hash():
                return False
            # Signature check
            expected = hashlib.sha256(
                f"{self.blocks[i].compute_hash()}{self.session_key}".encode()
            ).hexdigest()
            if self.blocks[i].signature != expected:
                return False
        return True

    def get_latest_intent(self) -> dict:
        return self.blocks[-1].parsed_intent if self.blocks else {}
