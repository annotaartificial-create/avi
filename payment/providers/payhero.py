from __future__ import annotations

import json
import logging
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


class PayHeroProvider(BasePaymentProvider):
    """
    PayHero Kenya payment adapter.
    Documentation: https://docs.payhero.co.ke
    Supports M-Pesa STK push via PayHero API v2 with Basic Authentication.
    """

    name = "payhero"

    def _get_credentials(self) -> dict[str, Any]:
        auth_token = getattr(settings, "PAYHERO_AUTH_TOKEN", "").strip()
        channel_id = getattr(settings, "PAYHERO_CHANNEL_ID", "").strip()
        base_url = getattr(settings, "PAYHERO_BASE_URL", "https://backend.payhero.co.ke").strip().rstrip("/")
        callback_url = getattr(settings, "PAYHERO_CALLBACK_URL", "").strip()

        if not auth_token:
            raise PaymentProviderError("PAYHERO_AUTH_TOKEN is missing or not configured in settings/.env")

        if not channel_id:
            raise PaymentProviderError("PAYHERO_CHANNEL_ID is missing or not configured in settings/.env")

        try:
            channel_id_int = int(channel_id)
        except ValueError:
            raise PaymentProviderError(f"PAYHERO_CHANNEL_ID must be an integer, got '{channel_id}'")

        # Format Basic Authorization header correctly
        if not auth_token.lower().startswith("basic "):
            auth_header = f"Basic {auth_token}"
        else:
            auth_header = auth_token

        return {
            "auth_header": auth_header,
            "channel_id": channel_id_int,
            "base_url": base_url,
            "callback_url": callback_url,
        }

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """
        Normalize Kenyan phone numbers to the format expected by PayHero (e.g. 07XXXXXXXX or 01XXXXXXXX).
        """
        digits = "".join(c for c in phone if c.isdigit())
        if digits.startswith("254") and len(digits) == 12:
            return "0" + digits[3:]
        if digits.startswith("0") and len(digits) == 10:
            return digits
        if len(digits) == 9:
            return "0" + digits
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
        Initiates an M-Pesa STK push request via PayHero:
        POST https://backend.payhero.co.ke/api/v2/payments
        """
        creds = self._get_credentials()
        clean_phone = self._normalize_phone(phone)
        effective_callback = callback_url or creds["callback_url"]

        payload = {
            "amount": int(amount_kes),
            "phone_number": clean_phone,
            "channel_id": creds["channel_id"],
            "provider": "m-pesa",
            "external_reference": str(reference),
            "customer_name": f"User {reference}",
            "callback_url": effective_callback,
        }

        headers = {
            "Authorization": creds["auth_header"],
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BinaryTrading/1.0",
        }

        url = f"{creds['base_url']}/api/v2/payments"

        logger.info(
            "PayHero initiate_deposit: phone=%s, amount=%s, ref=%s, channel=%s",
            clean_phone,
            amount_kes,
            reference,
            creds["channel_id"],
        )

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
        except requests.RequestException as exc:
            logger.error("PayHero STK push request failed: %s", exc)
            raise PaymentProviderError(f"PayHero network error: {exc}") from exc

        try:
            data = resp.json()
        except ValueError:
            logger.error("PayHero returned non-JSON response (%s): %s", resp.status_code, resp.text[:300])
            raise PaymentProviderError(
                f"PayHero returned invalid response (HTTP {resp.status_code})",
                code=str(resp.status_code),
            )

        if resp.status_code not in (200, 201):
            err_msg = (
                data.get("error_message")
                or data.get("message")
                or data.get("detail")
                or f"PayHero STK error (HTTP {resp.status_code})"
            )
            logger.error("PayHero STK initiation rejected: %s", data)
            raise PaymentProviderError(err_msg, code=str(resp.status_code), payload=data)

        # Success shape: {"success": true, "status": "QUEUED", "reference": "E8UWT7CLUW", "CheckoutRequestID": "ws_CO_..."}
        # Also supports nested "response" dictionary: {"response": {"CheckoutRequestID": "...", "Reference": "..."}}
        resp_data = data.get("response") if isinstance(data.get("response"), dict) else data
        checkout_id = str(
            resp_data.get("CheckoutRequestID")
            or resp_data.get("checkout_request_id")
            or data.get("CheckoutRequestID")
            or data.get("checkout_request_id")
            or ""
        ).strip()
        payhero_ref = str(
            resp_data.get("Reference")
            or resp_data.get("reference")
            or data.get("reference")
            or data.get("Reference")
            or ""
        ).strip()
        status_val = str(resp_data.get("status") or data.get("status") or "").upper()

        if not checkout_id and not payhero_ref and not data.get("success"):
            err_msg = data.get("error_message") or data.get("message") or "STK push was not queued by PayHero"
            raise PaymentProviderError(err_msg, payload=data)

        message = (
            f"STK push sent. Please check your phone ({clean_phone}) to enter your M-Pesa PIN."
        )

        return DepositInitiateResult(
            success=True,
            reference=reference,
            provider_reference=checkout_id or payhero_ref,
            resource_location=payhero_ref or checkout_id,
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
        Query PayHero for transaction status:
        GET https://backend.payhero.co.ke/api/v2/transaction-status?reference=<reference>
        Tries PayHero internal reference, external reference, and CheckoutRequestID.
        If transaction is not yet indexed or found on PayHero, safely returns pending status.
        """
        creds = self._get_credentials()

        headers = {
            "Authorization": creds["auth_header"],
            "Accept": "application/json",
            "User-Agent": "BinaryTrading/1.0",
        }
        url = f"{creds['base_url']}/api/v2/transaction-status"

        # Candidates to try in priority order
        candidates: list[str] = []
        for cand in [resource_location, reference, provider_reference]:
            cand_str = str(cand or "").strip()
            if cand_str and cand_str not in candidates:
                candidates.append(cand_str)

        if not candidates:
            raise PaymentProviderError("A valid reference or CheckoutRequestID is required to query PayHero")

        data: dict[str, Any] = {}
        last_http_code = 200

        for ref_to_query in candidates:
            try:
                resp = requests.get(url, params={"reference": ref_to_query}, headers=headers, timeout=25)
                last_http_code = resp.status_code
            except requests.RequestException as exc:
                logger.error("PayHero status query network error for %s: %s", ref_to_query, exc)
                continue

            if resp.status_code == 404:
                continue

            try:
                resp_json = resp.json()
            except ValueError:
                continue

            err_text = str(
                resp_json.get("error_message")
                or resp_json.get("message")
                or resp_json.get("error")
                or ""
            ).lower()

            if "not found" in err_text:
                continue

            if resp.status_code == 200:
                data = resp_json
                break

        # If all candidates returned 404 or "not found", payment is still pending/unindexed with gateway
        if not data:
            return TransactionStatusResult(
                status="pending",
                provider_reference=provider_reference or resource_location,
                reason="Transaction is still processing on M-Pesa / PayHero. Please wait a moment and click Check Status again.",
                raw_response={"status_code": last_http_code, "note": "Transaction not yet indexed by gateway"},
            )

        # PayHero transaction-status endpoint returns:
        # {
        #   "success": true,               <-- Indicates the API query operation succeeded (found the record)
        #   "status": "FAILED" | "SUCCESS" <-- The ACTUAL M-Pesa transaction outcome!
        #   "third_party_reference": "SKQ..." (M-Pesa receipt code if paid, empty if failed)
        # }
        raw_status = str(data.get("status") or "").strip().upper()

        receipt_number = str(
            data.get("third_party_reference")
            or data.get("provider_reference")
            or data.get("MpesaReceiptNumber")
            or data.get("payment_reference")
            or ""
        ).strip()

        checkout_id = str(data.get("CheckoutRequestID") or provider_reference or "").strip()

        if raw_status == "SUCCESS":
            return TransactionStatusResult(
                status="paid",
                provider_reference=checkout_id,
                receipt_number=receipt_number,
                reason="Payment confirmed via PayHero transaction query",
                raw_response=data,
            )

        if raw_status in ("FAILED", "REJECTED", "CANCELLED"):
            return TransactionStatusResult(
                status="rejected",
                provider_reference=checkout_id,
                receipt_number=receipt_number,
                reason=f"Payment cancelled/failed on PayHero (Status: {raw_status})",
                raw_response=data,
            )

        # Default / QUEUED / PENDING
        return TransactionStatusResult(
            status="pending",
            provider_reference=checkout_id,
            receipt_number=receipt_number,
            reason=f"Payment is {raw_status or 'pending'} with PayHero",
            raw_response=data,
        )

    def parse_webhook(
        self,
        raw_body: bytes | str | dict | None = None,
        headers: dict | None = None,
        **kwargs,
    ) -> WebhookParseResult:
        if raw_body is None:
            raw_body = kwargs.get("raw_body", {})
        """
        Parses incoming PayHero STK callback:
        {
          "forward_url": "",
          "response": {
            "Amount": 10,
            "CheckoutRequestID": "ws_CO_14012024103543427709099876",
            "ExternalReference": "INV-009",
            "MerchantRequestID": "3202-70921557-1",
            "MpesaReceiptNumber": "SAE3YULR0Y",
            "Phone": "+254709099876",
            "ResultCode": 0,
            "ResultDesc": "The service request is processed successfully.",
            "Status": "Success"
          },
          "status": true
        }
        """
        if isinstance(raw_body, dict):
            payload = raw_body
        else:
            try:
                body_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
                payload = json.loads(body_str)
            except Exception as exc:
                raise PaymentProviderError(f"Could not parse PayHero webhook JSON: {exc}") from exc

        # Handle nested "response" object or flat payload
        resp_obj = payload.get("response") if isinstance(payload.get("response"), dict) else payload

        external_ref = str(
            resp_obj.get("ExternalReference")
            or resp_obj.get("external_reference")
            or resp_obj.get("user_reference")
            or resp_obj.get("MerchantRequestID")
            or payload.get("ExternalReference")
            or payload.get("external_reference")
            or payload.get("reference")
            or payload.get("MerchantRequestID")
            or ""
        ).strip()

        checkout_id = str(
            resp_obj.get("CheckoutRequestID")
            or resp_obj.get("checkout_request_id")
            or payload.get("CheckoutRequestID")
            or payload.get("checkout_request_id")
            or ""
        ).strip()

        receipt_number = str(
            resp_obj.get("MpesaReceiptNumber")
            or resp_obj.get("mpesa_receipt_number")
            or resp_obj.get("providerReference")
            or resp_obj.get("provider_reference")
            or ""
        ).strip()

        result_code = resp_obj.get("ResultCode")
        if result_code is None:
            result_code = payload.get("ResultCode")

        status_text = str(
            resp_obj.get("Status")
            or resp_obj.get("status")
            or ""
        ).strip().lower()

        result_desc = str(
            resp_obj.get("ResultDesc")
            or resp_obj.get("result_desc")
            or resp_obj.get("message")
            or payload.get("message")
            or status_text
            or "Processed"
        ).strip()

        # Strict failure check first:
        # - ResultCode is provided and not 0 (e.g. 1032 user cancelled, 1 insufficient funds, 2001 wrong PIN)
        # - Status text is explicitly failed/cancelled/rejected/error
        # - paymentSuccess is explicitly False
        is_explicitly_failed = (
            (result_code is not None and str(result_code).strip() not in ("0", ""))
            or status_text in ("failed", "cancelled", "canceled", "rejected", "error", "unsuccessful")
            or payload.get("paymentSuccess") is False
        )

        # Explicit success check:
        # - ResultCode is 0 or "0"
        # - Status text is success/successful/paid
        # - paymentSuccess is True
        is_explicitly_success = (
            (result_code == 0 or str(result_code).strip() == "0")
            or status_text in ("success", "successful", "paid")
            or payload.get("paymentSuccess") is True
        )

        if is_explicitly_failed:
            normalized_status = "rejected"
        elif is_explicitly_success:
            normalized_status = "paid"
        else:
            normalized_status = "pending"

        return WebhookParseResult(
            reference=external_ref,
            status=normalized_status,
            provider_reference=checkout_id,
            receipt_number=receipt_number,
            reason=result_desc,
            raw_response=payload,
        )
