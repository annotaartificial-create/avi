from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.conf import settings

from .base import (
    BasePaymentProvider,
    DepositInitiateResult,
    PaymentProviderError,
    TransactionStatusResult,
    WebhookParseResult,
)

logger = logging.getLogger(__name__)

# Resilient HTTP request helper: uses `requests` if available, otherwise `urllib.request`
try:
    import requests
except ImportError:
    requests = None

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _http_post(url: str, json_data: dict | None = None, headers: dict | None = None, timeout: int = 30) -> dict[str, Any]:
    if requests is not None:
        resp = requests.post(url, json=json_data, headers=headers or {}, timeout=timeout)
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    # Fallback to standard library urllib
    req_headers = {"Accept": "application/json", "User-Agent": "Avingine/1.0"}
    if headers:
        req_headers.update(headers)
    body = None
    if json_data is not None:
        body = json.dumps(json_data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = Request(url, data=body, headers=req_headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw_err = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return json.loads(raw_err)
        except Exception:
            return {"errorMessage": str(exc), "raw": raw_err, "status_code": exc.code}
    except Exception as exc:
        raise PaymentProviderError(f"Daraja network error: {exc}") from exc


def _http_get(url: str, headers: dict | None = None, timeout: int = 30) -> dict[str, Any]:
    if requests is not None:
        resp = requests.get(url, headers=headers or {}, timeout=timeout)
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text, "status_code": resp.status_code}

    req_headers = {"Accept": "application/json", "User-Agent": "Avingine/1.0"}
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raw_err = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return json.loads(raw_err)
        except Exception:
            return {"errorMessage": str(exc), "raw": raw_err, "status_code": exc.code}
    except Exception as exc:
        raise PaymentProviderError(f"Daraja network error: {exc}") from exc


class DarajaProvider(BasePaymentProvider):
    """
    Safaricom Daraja API payment adapter for M-Pesa STK Push. sss
    All communication with Safaricom Daraja is self-contained in this module.
    """

    name = "daraja"

    def _get_credentials(self) -> dict[str, str]:
        env = getattr(settings, "DARAJA_ENVIRONMENT", "sandbox").strip().lower()
        consumer_key = getattr(settings, "DARAJA_CONSUMER_KEY", "").strip()
        consumer_secret = getattr(settings, "DARAJA_CONSUMER_SECRET", "").strip()
        till_number = getattr(settings, "DARAJA_TILL_NUMBER", "").strip()
        tx_type = getattr(settings, "DARAJA_TRANSACTION_TYPE", "CustomerPayBillOnline").strip()
        passkey = getattr(settings, "DARAJA_PASSKEY", "").strip()
        callback_url = getattr(settings, "DARAJA_CALLBACK_URL", "").strip()

        if not consumer_key or not consumer_secret:
            raise PaymentProviderError("Safaricom Daraja CONSUMER_KEY and CONSUMER_SECRET are required in settings/.env")
        if not passkey:
            raise PaymentProviderError("Safaricom Daraja PASSKEY is required in settings/.env")

        base_url = "https://api.safaricom.co.ke" if env in ("production", "prod") else "https://sandbox.safaricom.co.ke"

        return {
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
            "shortcode": shortcode,
            "till_number": till_number,
            "tx_type": tx_type,
            "passkey": passkey,
            "callback_url": callback_url,
            "base_url": base_url,
        }

    def _get_access_token(self) -> str:
        creds = self._get_credentials()
        raw_creds = f"{creds['consumer_key']}:{creds['consumer_secret']}".encode("utf-8")
        auth_header = f"Basic {base64.b64encode(raw_creds).decode('utf-8')}"
        url = f"{creds['base_url']}/oauth/v1/generate?grant_type=client_credentials"

        data = _http_get(url, headers={"Authorization": auth_header})
        token = data.get("access_token")
        if not token:
            err_msg = data.get("errorMessage") or "Failed to obtain Safaricom Daraja access token."
            raise PaymentProviderError(err_msg, payload=data)
        return token

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        digits = "".join(c for c in phone if c.isdigit())
        if digits.startswith("0") and len(digits) == 10:
            return "254" + digits[1:]
        if digits.startswith("254") and len(digits) == 12:
            return digits
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
        creds = self._get_credentials()
        token = self._get_access_token()
        clean_phone = self._normalize_phone(phone)
        effective_callback = callback_url or creds["callback_url"]

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password_raw = f"{creds['shortcode']}{creds['passkey']}{timestamp}".encode("utf-8")
        password = base64.b64encode(password_raw).decode("utf-8")

        party_b = creds["till_number"] if (creds["tx_type"] == "CustomerBuyGoodsOnline" and creds["till_number"]) else creds["shortcode"]
        payload = {
            "BusinessShortCode": creds["shortcode"],
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": creds["tx_type"],
            "Amount": int(amount_kes),
            "PartyA": clean_phone,
            "PartyB": '247247',
            "PhoneNumber": clean_phone,
            "CallBackURL": effective_callback,
            "AccountReference": '777018140279',
            "TransactionDesc": "Deposit",
        }

        url = f"{creds['base_url']}/mpesa/stkpush/v1/processrequest"
        data = _http_post(url, json_data=payload, headers={"Authorization": f"Bearer {token}"})

        checkout_id = str(data.get("CheckoutRequestID") or "").strip()
        response_code = str(data.get("ResponseCode") or "")
        customer_message = str(
            data.get("CustomerMessage")
            or data.get("ResponseDescription")
            or "STK push sent. Check your phone to enter your M-Pesa PIN."
        )

        if response_code != "0" and not checkout_id:
            err_msg = data.get("errorMessage") or data.get("ResponseDescription") or "STK push was rejected by Safaricom"
            raise PaymentProviderError(err_msg, code=response_code, payload=data)

        return DepositInitiateResult(
            success=True,
            reference=reference,
            provider_reference=checkout_id,
            resource_location="",
            message=customer_message,
            raw_response=data,
        )

    def query_deposit(
        self,
        *,
        reference: str = "",
        resource_location: str = "",
        provider_reference: str = "",
    ) -> TransactionStatusResult:
        checkout_id = provider_reference or reference
        if not checkout_id:
            raise PaymentProviderError("CheckoutRequestID is required for Daraja status query")

        creds = self._get_credentials()
        token = self._get_access_token()

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password_raw = f"{creds['shortcode']}{creds['passkey']}{timestamp}".encode("utf-8")
        password = base64.b64encode(password_raw).decode("utf-8")

        payload = {
            "BusinessShortCode": creds["shortcode"],
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_id,
        }

        url = f"{creds['base_url']}/mpesa/stkpushquery/v1/query"
        data = _http_post(url, json_data=payload, headers={"Authorization": f"Bearer {token}"})

        result_code = data.get("ResultCode")
        result_desc = str(data.get("ResultDesc") or data.get("ResponseDescription") or "")

        if result_code is not None and str(result_code) == "0":
            return TransactionStatusResult(
                status="paid",
                provider_reference=checkout_id,
                receipt_number="",
                reason=result_desc or "Payment confirmed via Daraja query",
                raw_response=data,
            )

        failure_codes = {"1", "1032", "1037", "2001", "1001"}
        if result_code is not None and str(result_code) in failure_codes:
            return TransactionStatusResult(
                status="rejected",
                provider_reference=checkout_id,
                receipt_number="",
                reason=result_desc or f"Daraja STK failed (ResultCode {result_code})",
                raw_response=data,
            )

        return TransactionStatusResult(
            status="pending",
            provider_reference=checkout_id,
            receipt_number="",
            reason=result_desc or "Transaction still in progress",
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

        stk_callback = payload.get("Body", {}).get("stkCallback", {})
        result_code = stk_callback.get("ResultCode")
        result_desc = str(stk_callback.get("ResultDesc") or "")
        checkout_id = str(stk_callback.get("CheckoutRequestID") or "")

        receipt = ""
        items = stk_callback.get("CallbackMetadata", {}).get("Item", []) or []
        for item in items:
            if item.get("Name") == "MpesaReceiptNumber":
                receipt = str(item.get("Value") or "")
                break

        if result_code is not None and str(result_code) == "0":
            status = "paid"
        else:
            status = "rejected"

        return WebhookParseResult(
            reference=checkout_id,
            status=status,
            provider_reference=checkout_id,
            receipt_number=receipt,
            reason=result_desc,
            raw_response=payload,
        )
