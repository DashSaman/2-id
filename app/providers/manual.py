from __future__ import annotations

from .base import AppleAccountRequest, AppleAccountResult


class ManualAppleProvider:
    """Production placeholder until an approved real provider is connected."""

    def create_account(self, request: AppleAccountRequest) -> AppleAccountResult:
        return AppleAccountResult("ACTION_REQUIRED", "MANUAL_FULFILLMENT_REQUIRED", retryable=False)
