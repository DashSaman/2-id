from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AppleAccountRequest:
    email: str
    password: str
    first_name: str
    last_name: str


@dataclass(frozen=True)
class AppleAccountResult:
    status: str
    code: str | None = None
    retryable: bool = False


class AppleProvider(Protocol):
    def create_account(self, request: AppleAccountRequest) -> AppleAccountResult: ...
