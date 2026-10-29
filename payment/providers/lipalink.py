from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
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

logger = logging.getLogger(__name__)


class LipaLinkProvider(BasePaymentProvider):
    """
    LipaLink Kenya payment adapter.
    Documentation: https://lipalink.co.ke/docs
    Supports M-Pesa STK push, transaction status polling, and HMAC-verified webhooks.
    """

    name = "lipalink"

    def _get_credentials(self) -> dict[str, Any]:
        api_key = (
            getattr(settings, "LIPALINK_API_KEY", "").strip()
            or os.getenv("LIPALINK_API_KEY", "").strip()
        )
        business_id = (
            getattr(settings, "LIPALINK_BUSINESS_ID", "").strip()
            or os.getenv("LIPALINK_BUSINESS_ID", "").strip()
        )
        base_url = (
            getattr(settings, "LIPALINK_BASE_URL", "https://lipalink.co.ke").strip().rstrip("/")
            or "https://lipalink.co.ke"
        )

        if not api_key:
            raise PaymentProviderError("LIPALINK_API_KEY is missing or not configured in settings/.env")

        if not business_id:
            raise PaymentProviderError("LIPALINK_BUSINESS_ID is missing or not configured in settings/.env")

        try:
            business_id_int = int(business_id)
        except ValueError:
            raise PaymentProviderError(f"LIPALINK_BUSINESS_ID must be an integer, got '{business_id}'")

        return {
            "api_key": api_key,
            "business_id": business_id_int,
            "base_url": base_url,
        }

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """
        Normalize Kenyan phone numbers to format accepted by LipaLink:
        2547XXXXXXXX or 2541XXXXXXXX. (07... and 01... are converted to 254...)
        """
        digits = "".join(c for c in phone if c.isdigit())
        if digits.startswith("254") and len(digits) == 12:
            return digits
        if digits.startswith("0") and len(digits) == 10:
            return "254" + digits[1:]
        if len(digits) == 9:
            return "254" + digits
        return digits

    def initiate_deposit(
        self,
        *,
        reference: str,
        phone: str,
        amount_kes: int,
        amount_usd: Decimal,
        callback_url: str = "",
    ) -> DepositInitiateResult:
        """
        Initiates an M-Pesa STK push request via LipaLink:
        POST https://lipalink.co.ke/api/stk_push.php
        """
        creds = self._get_credentials()
        clean_phone = self._normalize_phone(phone)

        # LipaLink requires letters/digits, <= 20 characters for reference
        clean_ref = re.sub(r"[^a-zA-Z0-9_-]", "", str(reference))[:20]

        payload = {
            "amount": int(amount_kes),
            "msisdn": clean_phone,
            "business_id": creds["business_id"],
            "reference": clean_ref,
            "description": f"Deposit {clean_ref}",
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Api-Key": creds["api_key"],
            "User-Agent": "Avingine/1.0",
        }

        url = f"{creds['base_url']}/api/stk_push.php"

        logger.info(
            "LipaLink initiate_deposit: phone=%s, amount=%s, ref=%s, business_id=%s",
            clean_phone,
            amount_kes,
            clean_ref,
            creds["business_id"],
        )

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as exc:
            logger.error("LipaLink STK push network error: %s", exc)
            raise PaymentProviderError(f"LipaLink network error: {exc}") from exc

        try:
            data = resp.json()
        except ValueError:
            logger.error("LipaLink returned non-JSON response (%s): %s", resp.status_code, resp.text[:300])
            raise PaymentProviderError(
                f"LipaLink returned invalid response (HTTP {resp.status_code})",
                code=str(resp.status_code),
            )

        if resp.status_code not in (200, 201) or not data.get("success"):
            err_msg = (
                data.get("message")
                or data.get("error")
                or data.get("error_message")
                or f"LipaLink STK initiation error (HTTP {resp.status_code})"
            )
            logger.error("LipaLink STK push rejected: %s", data)
            raise PaymentProviderError(err_msg, code=str(resp.status_code), payload=data)

        # Response shape:
        # { "success": true, "transaction_id": "PFX20260101ABCDEF", "status": "Pending", "message": "STK push sent..." }
        transaction_id = str(data.get("transaction_id") or "").strip()
        message = str(data.get("message") or f"STK push sent. Please check phone {clean_phone} to enter your M-Pesa PIN.")

        return DepositInitiateResult(
            success=True,
            reference=reference,
            provider_reference=transaction_id,
            resource_location=transaction_id,
            message=message,
            raw_response=data,
        )

    def query_deposit(
        self,
        *,
        reference: str = "",
        resource_location: str = "",
        provider_reference: str = "",
    ) -> TransactionStatusResult:
        """
        Query LipaLink for transaction status:
        GET https://lipalink.co.ke/api/transaction_status.php?transaction_id=PFX...
        """
        creds = self._get_credentials()

        headers = {
            "Accept": "application/json",
            "X-Api-Key": creds["api_key"],
            "User-Agent": "Avingine/1.0",
        }
        url = f"{creds['base_url']}/api/transaction_status.php"

        # Candidates to try (transaction_id is the primary lookup key)
        candidates: list[str] = []
        for cand in [provider_reference, resource_location, reference]:
            cand_str = str(cand or "").strip()
            if cand_str and cand_str not in candidates:
                candidates.append(cand_str)

        if not candidates:
            raise PaymentProviderError("A valid transaction_id or reference is required to query LipaLink")

        data: dict[str, Any] = {}
        last_http_code = 200

        for ref_to_query in candidates:
            try:
                resp = requests.get(url, params={"transaction_id": ref_to_query}, headers=headers, timeout=25)
                last_http_code = resp.status_code
            except requests.RequestException as exc:
                logger.error("LipaLink status query network error for %s: %s", ref_to_query, exc)
                continue

            if resp.status_code == 404:
                continue

            try:
                resp_json = resp.json()
            except ValueError:
                continue

            # Check if successful response received
            if resp.status_code in (200, 201) and resp_json.get("success"):
                data = resp_json
                break

        if not data:
            return TransactionStatusResult(
                status="pending",
                provider_reference=provider_reference or resource_location,
                reason="Transaction is still processing on M-Pesa / LipaLink. Please wait a moment and click Check Status again.",
                raw_response={"status_code": last_http_code, "note": "Transaction not yet indexed by gateway"},
            )

        # LipaLink status can be "Success", "Failed", "Cancelled", or "Pending"
        raw_status = str(data.get("status") or "").strip().upper()
        receipt_number = str(data.get("mpesa_receipt") or data.get("receipt_number") or "").strip()
        tx_id = str(data.get("transaction_id") or provider_reference or "").strip()
        result_desc = str(data.get("result_desc") or data.get("message") or f"Status: {raw_status}").strip()

        if raw_status == "SUCCESS":
            return TransactionStatusResult(
                status="paid",
                provider_reference=tx_id,
                receipt_number=receipt_number or tx_id,
                reason="Payment confirmed via LipaLink transaction status query",
                raw_response=data,
            )

        if raw_status in ("FAILED", "CANCELLED", "CANCELED", "REJECTED"):
            return TransactionStatusResult(
                status="rejected",
                provider_reference=tx_id,
                receipt_number=receipt_number,
                reason=result_desc or f"Payment failed on LipaLink (Status: {raw_status})",
                raw_response=data,
            )

        return TransactionStatusResult(
            status="pending",
            provider_reference=tx_id,
            receipt_number=receipt_number,
            reason=result_desc or "Payment is still processing on LipaLink",
            raw_response=data,
        )

    def parse_webhook(
        self,
        raw_body: bytes | str | dict | None = None,
        headers: dict | None = None,
        **kwargs,
    ) -> WebhookParseResult:
        """
        Parses incoming LipaLink webhook callback:
        {
          "event": "payment.success",
          "transaction_id": "PFX20260101ABCDEF",
          "status": "Success",
          "amount": 1500,
          "currency": "KES",
          "amount_kes": 1500,
          "fx_rate": 1,
          "msisdn": "254712345678",
          "mpesa_receipt": "TJ7ABC12XY",
          "reference": "ORDER-001",
          "business_id": 12,
          "country": "KEN",
          "provider": "MPESA",
          "transaction_date": "2026-10-07 10:14:00",
          "test": false
        }

        Verifies HMAC-SHA256 signature when X-Pesaflux-Signature header is provided:
        X-Pesaflux-Signature: t=1760000000,v1=9f2c...
        Signature = HMAC-SHA256("<t>.<raw body>", key=API_KEY)
        """
        if raw_body is None:
            raw_body = kwargs.get("raw_body", {})

        body_bytes: bytes = b""
        payload: dict[str, Any] = {}

        if isinstance(raw_body, dict):
            payload = raw_body
            body_bytes = json.dumps(raw_body).encode("utf-8")
        elif not raw_body:
            payload = {}
            body_bytes = b""
        else:
            try:
                body_bytes = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode("utf-8")
                body_str = body_bytes.decode("utf-8")
                payload = json.loads(body_str) if body_str.strip() else {}
            except Exception as exc:
                raise PaymentProviderError(f"Could not parse LipaLink webhook JSON: {exc}") from exc

        # Verify HMAC-SHA256 signature if header is present
        norm_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        sig_header = norm_headers.get("x-pesaflux-signature") or norm_headers.get("x-signature")
        api_key = (
            getattr(settings, "LIPALINK_API_KEY", "").strip()
            or os.getenv("LIPALINK_API_KEY", "").strip()
        )

        if sig_header and api_key and body_bytes:
            try:
                # Format: t=1760000000,v1=9f2c...
                parts = dict(p.strip().split("=", 1) for p in sig_header.split(",") if "=" in p)
                t_val = parts.get("t")
                v1_val = parts.get("v1")
                if t_val and v1_val:
                    body_str = body_bytes.decode("utf-8")
                    computed_mac = hmac.new(
                        api_key.encode("utf-8"),
                        f"{t_val}.{body_str}".encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest()
                    if not hmac.compare_digest(computed_mac, v1_val):
                        logger.warning(
                            "LipaLink webhook signature mismatch. Computed: %s, Received: %s",
                            computed_mac,
                            v1_val,
                        )
                        raise PaymentProviderError("Invalid LipaLink webhook HMAC signature")
            except PaymentProviderError:
                raise
            except Exception as sig_err:
                logger.warning("Error validating LipaLink signature: %s", sig_err)

        external_ref = str(
            payload.get("reference")
            or payload.get("external_reference")
            or payload.get("order_id")
            or ""
        ).strip()

        transaction_id = str(
            payload.get("transaction_id")
            or payload.get("provider_reference")
            or payload.get("id")
            or ""
        ).strip()

        receipt_number = str(
            payload.get("mpesa_receipt")
            or payload.get("receipt_number")
            or payload.get("provider_reference")
            or ""
        ).strip()

        status_text = str(payload.get("status") or "").strip().lower()
        event_text = str(payload.get("event") or "").strip().lower()
        result_desc = str(payload.get("result_desc") or payload.get("message") or f"Status: {status_text}").strip()

        # Determine normalized status:
        # LipaLink sends status "Success" or event "payment.success"
        if status_text in ("success", "paid", "completed") or event_text == "payment.success":
            normalized_status = "paid"
        elif status_text in ("failed", "cancelled", "canceled", "rejected", "error") or event_text == "payment.failed":
            normalized_status = "rejected"
        else:
            normalized_status = "pending"

        return WebhookParseResult(
            reference=external_ref,
            status=normalized_status,
            provider_reference=transaction_id,
            receipt_number=receipt_number or transaction_id,
            reason=result_desc,
            raw_response=payload,
        )

