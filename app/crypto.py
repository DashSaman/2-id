from __future__ import annotations

import base64
import hashlib
import hmac
import json
from cryptography.fernet import Fernet


def derive_test_key(seed: str) -> str:
    digest = hashlib.sha256(seed.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


class PayloadCrypto:
    def __init__(self, key: str):
        if not key:
            raise RuntimeError("APP_ENCRYPTION_KEY is required")
        self.fernet = Fernet(key.encode())

    def encrypt(self, payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        return self.fernet.encrypt(raw).decode()

    def decrypt(self, token: str) -> dict:
        return json.loads(self.fernet.decrypt(token.encode()).decode())


def fingerprint(payload: dict, key: str) -> str:
    safe = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hmac.new(key.encode(), safe, hashlib.sha256).hexdigest()
