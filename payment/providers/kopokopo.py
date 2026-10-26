from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.conf import settings
import requests

from .base import (
    BasePaymentProvider,
    DepositInitiateResult,
    PaymentProviderError,
    TransactionStatusResult,
    WebhookParseResult,
)


class KopoKopoProvider(BasePaymentProvider):
    name = "kopokopo"

    def _get_setting(self, name: str) -> str:
        val = getattr(settings, name, None)
        if not val:
            raise PaymentProviderError(f"{name} is not configured in settings")
        return str(val).strip()

    def _get_credentials(self) -> dict[str, str]:
        env = getattr(settings, "KOPOKOPO_ENVIRONMENT", "sandbox")
        prefix = f"KOPOKOPO_{'SANDBOX' if env == 'sandbox' else 'PROD'}"

        client_id = getattr(settings, f"{prefix}_CLIENT_ID", None) or getattr(settings, "KOPOKOPO_PROD_CLIENT_ID", "")
        client_secret = getattr(settings, f"{prefix}_CLIENT_SECRET", None) or getattr(settings, "KOPOKOPO_PROD_CLIENT_SECRET", "")
        base_url = getattr(settings, f"{prefix}_BASE_URL", None) or getattr(settings, "KOPOKOPO_PROD_BASE_URL", "https://app.kopokopo.com")
        till = getattr(settings, f"{prefix}_TILL", None) or getattr(settings, "KOPOKOPO_PROD_TILL", "")
        callback_url = getattr(settings, f"{prefix}_CALLBACK_URL", None) or getattr(settings, "KOPOKOPO_PROD_CALLBACK_URL", "")

        if not client_id or not client_secret:
            raise PaymentProviderError("KopoKopo API credentials (CLIENT_ID / CLIENT_SECRET) are missing")

        return {
            "client_id": str(client_id).strip(),
            "client_secret": str(client_secret).strip(),
            "base_url": str(base_url).strip().rstrip("/"),
            "till": str(till).strip(),
            "callback_url": str(callback_url).strip(),
        }

    def _get_access_token(self) -> str:
        credentials = self._get_credentials()
        url = "https://app.kopokopo.com/oauth/token"
        payload = {
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "grant_type": "client_credentials",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "BinaryApp/1.0",
        }
        try:
            response = requests.post(url, data=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data["access_token"]
        except Exception as exc:
            raise PaymentProviderError(f"Failed to obtain KopoKopo access token: {exc}") from exc

    def initiate_deposit(
        self,
        *,
        reference: str,
        phone: str,
        amount_kes: int,
        amount_usd: Decimal,
        callback_url: str = "",
    ) -> DepositInitiateResult:
        credentials = self._get_credentials()
        access_token = self._get_access_token()

        url = f"{credentials['base_url']}/api/v2/incoming_payments"
        effective_callback = callback_url or credentials["callback_url"]

        payload = {
            "payment_channel": "M-PESA STK PUSH",
            "till_number": credentials["till"],
            "subscriber": {
                "phone_number": phone,
            },
            "amount": {
                "currency": "KES",
                "value": amount_kes,
            },
            "metadata": {
                "reference": str(reference),
            },
            "_links": {
                "callback_url": effective_callback,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "BinaryApp/1.0",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=45)
        except Exception as exc:
            raise PaymentProviderError(f"Network error connecting to KopoKopo: {exc}") from exc

        if response.status_code != 201:
            try:
                data = response.json()
            except Exception:
                data = {}
            msg = data.get("message") or data.get("error") or response.text or "STK push was rejected"
            raise PaymentProviderError(msg, code=str(response.status_code), payload=data)

        location = response.headers.get("Location") or ""
        if not location:
            raise PaymentProviderError("KopoKopo accepted STK request but did not return a resource location")

        return DepositInitiateResult(
            success=True,
            reference=reference,
            provider_reference=location,
            resource_location=location,
            message="STK push request sent. Enter M-Pesa PIN on your phone.",
            raw_response={"location": location, "status_code": response.status_code},
        )

    def query_deposit(
        self,
        *,
        reference: str = "",
        resource_location: str = "",
        provider_reference: str = "",
    ) -> TransactionStatusResult:
        location = resource_location or provider_reference
        if not location:
            raise PaymentProviderError("KopoKopo resource location is required for status query")

        access_token = self._get_access_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "BinaryApp/1.0",
        }

        try:
            response = requests.get(location, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise PaymentProviderError(f"Failed to query KopoKopo status: {exc}") from exc

        # Parse KopoKopo resource
        parsed = self.parse_webhook(raw_body=data)
        return TransactionStatusResult(
            status=parsed.status,
            provider_reference=location,
            receipt_number=parsed.receipt_number,
            reason=parsed.reason,
            raw_response=data,
        )

    def parse_webhook(
        self,
        *,
        raw_body: bytes | str | dict,
        headers: dict | None = None,
    ) -> WebhookParseResult:
        if isinstance(raw_body, (bytes, bytearray)):
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except Exception:
                payload = {}
        elif isinstance(raw_body, str):
            try:
                payload = json.loads(raw_body)
            except Exception:
                payload = {}
        elif isinstance(raw_body, dict):
            payload = raw_body
        else:
            payload = {}

        data = payload.get("data") or {}
        attributes = data.get("attributes") or {}
        raw_status = str(attributes.get("status") or "").strip()

        metadata = attributes.get("metadata") or {}
        reference = str(metadata.get("reference") or "")

        event = attributes.get("event") or {}
        errors = event.get("errors") or []
        resource = event.get("resource") or {}
        receipt = str(resource.get("reference") or resource.get("transaction_reference") or "")

        if raw_status.lower() in ("success", "paid"):
            status = "paid"
            reason = str(resource.get("status") or "Payment completed successfully")
        elif raw_status.lower() in ("failed", "rejected"):
            status = "rejected"
            reason = "; ".join(str(e) for e in errors) if errors else "Payment failed"
        else:
            status = "pending"
            reason = "Payment is pending customer confirmation"

        return WebhookParseResult(
            reference=reference,
            status=status,
            provider_reference=str(data.get("id") or ""),
            receipt_number=receipt,
            reason=reason,
            raw_response=payload,
        )
