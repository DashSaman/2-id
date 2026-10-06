class ManualPaymentProvider:
    def create_payment(self, *, amount: int, currency: str, reference: str) -> dict:
        return {"status": "manual_admin_funding_only", "amount": amount, "currency": currency, "reference": reference}
