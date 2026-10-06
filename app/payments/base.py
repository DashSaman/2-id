from typing import Protocol


class PaymentProvider(Protocol):
    def create_payment(self, *, amount: int, currency: str, reference: str) -> dict: ...
