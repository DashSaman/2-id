from __future__ import annotations

from .base import AppleAccountRequest, AppleAccountResult


class MockAppleProvider:
    def __init__(self, mode: str = "created"):
        self.mode = mode.lower()

    def create_account(self, request: AppleAccountRequest) -> AppleAccountResult:
        mode = self.mode
        local = request.email.split("@", 1)[0].lower()
        if "+phone" in local or mode == "phone":
            return AppleAccountResult("PHONE_VERIFICATION_REQUIRED", "PHONE_REQUIRED")
        if "+action" in local or mode == "action":
            return AppleAccountResult("ACTION_REQUIRED", "EMAIL_OTP_REQUIRED")
        if "+retry" in local or mode == "retry":
            return AppleAccountResult("FAILED", "TEMPORARY_PROVIDER_ERROR", retryable=True)
        if "+fail" in local or mode == "fail":
            return AppleAccountResult("FAILED", "PROVIDER_REJECTED")
        return AppleAccountResult("CREATED", "MOCK_CREATED")
