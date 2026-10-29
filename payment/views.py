from __future__ import annotations

import json
import logging
import os
import secrets
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import requests

from .models import PaymentLedger, Wallet
from .providers.factory import get_payment_provider
from .providers.base import PaymentProviderError

logger = logging.getLogger(__name__)


def send_mapp_withdrawal_notification(username: str, amount: Decimal | float | str) -> dict | None:
    """
    Sends a POST request to https://exavala.com/mapp/notify/ notifying the external server
    of a successful withdrawal with the username and amount in KES.
    """
    url = getattr(settings, "MAPP_NOTIFY_URL", "https://exavala.com/mapp/notify/")
    payload = {
        "username": str(username),
        "amount": str(amount),
    }
    try:
        logger.info("Sending mapp withdrawal notification to %s for username=%s, amount=%s", url, username, amount)
        resp = requests.post(url, data=payload, timeout=10)
        logger.info("mapp notification response [%s]: %s", resp.status_code, resp.text)
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}
    except Exception as exc:
        logger.error("Failed to send mapp withdrawal notification to %s for username %s: %s", url, username, exc, exc_info=True)
        return None


def _normalize_kenyan_phone(phone: str) -> str:
    """Normalizes phone string to standard Kenyan format."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("254") and len(digits) == 12:
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if len(digits) == 9:
        return "254" + digits
    return digits


@login_required
@require_POST
def initiate_deposit_view(request):
    """
    Initiates an M-Pesa STK push deposit for the authenticated user.
    Creates a PaymentLedger record in PENDING status and sends STK prompt via active provider.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request format. JSON expected."}, status=400)

    raw_phone = str(body.get("phone", "")).strip()
    raw_amount = body.get("amount")

    if not raw_phone:
        return JsonResponse({"success": False, "error": "Please enter your M-Pesa phone number."}, status=400)

    if not raw_amount:
        return JsonResponse({"success": False, "error": "Please specify a deposit amount."}, status=400)

    min_env = os.getenv("MIN_DEPOSIT_AMOUNT", "").strip()
    if min_env:
        try:
            min_deposit = Decimal(min_env)
        except Exception:
            min_deposit = getattr(settings, "MIN_DEPOSIT_AMOUNT", Decimal("10.00"))
    else:
        min_deposit = getattr(settings, "MIN_DEPOSIT_AMOUNT", Decimal("10.00"))
    max_deposit = getattr(settings, "MAX_DEPOSIT_AMOUNT", Decimal("150000.00"))

    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        if amount < min_deposit:
            min_str = f"{int(min_deposit)}" if min_deposit == int(min_deposit) else f"{min_deposit}"
            return JsonResponse({"success": False, "error": f"Minimum deposit amount is {min_str} KES."}, status=400)
        if amount > max_deposit:
            max_str = f"{int(max_deposit):,}" if max_deposit == int(max_deposit) else f"{max_deposit:,}"
            return JsonResponse({"success": False, "error": f"Maximum deposit amount is {max_str} KES."}, status=400)
    except (ValueError, InvalidOperation):
        return JsonResponse({"success": False, "error": "Invalid amount specified."}, status=400)

    clean_phone = _normalize_kenyan_phone(raw_phone)
    if len(clean_phone) != 12 or not clean_phone.startswith("254"):
        return JsonResponse({"success": False, "error": "Please provide a valid Kenyan phone number (e.g. 07XXXXXXXX or 01XXXXXXXX)."}, status=400)

    # Ensure user has a wallet
    wallet, _ = Wallet.objects.get_or_create(
        user=request.user,
        defaults={"balance": Decimal("0.00")}
    )

    # Generate unique system reference
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    reference = f"DEP-{timestamp}-{request.user.id}"

    # Resolve active payment provider
    try:
        provider = get_payment_provider()
    except Exception as exc:
        logger.error("Failed to resolve payment provider: %s", exc)
        return JsonResponse({"success": False, "error": f"Payment gateway configuration error: {exc}"}, status=500)

    # Create PaymentLedger entry
    ledger = PaymentLedger.objects.create(
        user=request.user,
        wallet=wallet,
        transaction_type=PaymentLedger.TransactionType.DEPOSIT,
        provider=provider.name,
        reference=reference,
        phone=clean_phone,
        amount=amount,
        currency="KES",
        status=PaymentLedger.Status.PENDING,
        raw_request={"phone": clean_phone, "amount": str(amount)},
    )

    # Build webhook callback URL (force https scheme so reverse proxies do not trigger 301/302 redirects)
    try:
        callback_url = request.build_absolute_uri(
            reverse("payment:webhook", kwargs={"provider_name": provider.name})
        )
        if callback_url.startswith("http://"):
            callback_url = "https://" + callback_url[7:]
    except Exception:
        callback_url = ""

    # Call provider adapter to initiate deposit
    try:
        result = provider.initiate_deposit(
            reference=reference,
            phone=clean_phone,
            amount_kes=int(amount),
            amount_usd=Decimal("0.00"),
            callback_url=callback_url,
        )

        ledger.provider_reference = result.provider_reference
        ledger.raw_response = result.raw_response
        ledger.description = result.message
        ledger.save(update_fields=["provider_reference", "raw_response", "description", "updated_at"])

        return JsonResponse({
            "success": True,
            "reference": reference,
            "provider": provider.name,
            "provider_reference": result.provider_reference,
            "message": result.message or f"STK push sent to {clean_phone}. Check your phone to enter your M-Pesa PIN.",
        })

    except PaymentProviderError as exc:
        logger.warning("Payment initiation rejected for ref %s: %s", reference, exc)
        ledger.mark_as_failed(reason=str(exc), raw_response=getattr(exc, "payload", {}))
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    except Exception as exc:
        logger.error("Unexpected error initiating deposit for ref %s: %s", reference, exc, exc_info=True)
        ledger.mark_as_failed(reason=f"System error: {exc}")
        return JsonResponse({"success": False, "error": f"Failed to initiate STK push: {exc}"}, status=500)


def _perform_direct_status_check(ledger: PaymentLedger) -> JsonResponse:
    """
    Directly queries the provider's status checking method (e.g. Daraja STK query, PayHero
    transaction status, or KopoKopo GET resource) instead of waiting for webhook callback.
    Called when callback is not received within specified time and user clicks 'Check Status'.
    """
    # 1. If already completed in DB (e.g. callback arrived in the meantime)
    if ledger.is_completed:
        return JsonResponse({
            "status": "COMPLETED",
            "reference": ledger.reference,
            "amount": float(ledger.amount),
            "receipt": ledger.receipt_number,
            "balance": float(ledger.wallet.available_balance),
            "message": "Deposit confirmed! Your wallet balance has been updated.",
        })

    # 2. If already marked failed in DB
    if ledger.is_failed:
        return JsonResponse({
            "status": "FAILED",
            "reference": ledger.reference,
            "message": ledger.error_message or "Payment was not completed. Please try again.",
        })

    # 3. Call the provider's direct query method
    try:
        provider = get_payment_provider(ledger.provider)

        # Extract internal provider reference from raw_response if present
        raw_ref = ""
        if isinstance(ledger.raw_response, dict):
            raw_ref = str(
                ledger.raw_response.get("reference")
                or ledger.raw_response.get("Reference")
                or ledger.raw_response.get("response", {}).get("Reference")
                or ledger.raw_response.get("response", {}).get("reference")
                or ""
            ).strip()

        query_result = provider.query_deposit(
            reference=ledger.reference,
            provider_reference=ledger.provider_reference,
            resource_location=raw_ref or ledger.provider_reference,
        )

        if query_result.status == "paid":
            receipt = query_result.receipt_number or ledger.provider_reference or ledger.reference
            ledger.mark_as_paid(
                receipt_number=receipt,
                raw_response=query_result.raw_response,
                reason=query_result.reason or "Payment confirmed via direct status query",
            )
            return JsonResponse({
                "status": "COMPLETED",
                "reference": ledger.reference,
                "amount": float(ledger.amount),
                "receipt": ledger.receipt_number,
                "balance": float(ledger.wallet.available_balance),
                "message": "Deposit confirmed! Your wallet balance has been updated.",
            })

        elif query_result.status == "rejected":
            ledger.mark_as_failed(
                reason=query_result.reason or "Payment was rejected or cancelled.",
                raw_response=query_result.raw_response,
            )
            return JsonResponse({
                "status": "FAILED",
                "reference": ledger.reference,
                "message": query_result.reason or "Payment was rejected or cancelled.",
            })

        else:
            return JsonResponse({
                "status": "PENDING",
                "reference": ledger.reference,
                "message": query_result.reason or "Waiting for PIN entry and M-Pesa confirmation...",
            })

    except PaymentProviderError as exc:
        logger.warning("Provider direct query error for ref %s: %s", ledger.reference, exc)
        return JsonResponse({
            "status": "PENDING",
            "reference": ledger.reference,
            "error": str(exc),
            "message": "Waiting for PIN entry and M-Pesa confirmation...",
        })
    except Exception as exc:
        logger.error("Unexpected error in direct status check for ref %s: %s", ledger.reference, exc, exc_info=True)
        return JsonResponse({
            "status": "PENDING",
            "reference": ledger.reference,
            "error": str(exc),
            "message": "Waiting for PIN entry and M-Pesa confirmation...",
        })


@login_required
@require_GET
def deposit_status_view(request, reference: str):
    """
    Polls the status of a deposit transaction.
    1. Checks local database (PaymentLedger) to see if transaction is already completed or failed (e.g. via webhook).
    2. If still pending locally, queries the provider's check status function.
    3. Updates the transaction using the result and returns the completed or failed result to frontend.
    4. If provider says transaction is still pending, returns PENDING so frontend can send the next poll.
    """
    ledger = get_object_or_404(PaymentLedger, reference=reference, user=request.user)

    # 1. Local check: If already completed, return immediately
    if ledger.is_completed:
        return JsonResponse({
            "status": "COMPLETED",
            "reference": ledger.reference,
            "amount": float(ledger.amount),
            "receipt": ledger.receipt_number,
            "balance": float(ledger.wallet.available_balance),
            "message": "Deposit confirmed! Your wallet balance has been updated.",
        })

    # 2. Local check: If failed, return failure state
    if ledger.is_failed:
        return JsonResponse({
            "status": "FAILED",
            "reference": ledger.reference,
            "message": ledger.error_message or "Payment was not completed. Please try again.",
        })

    # 3. Before telling frontend the transaction is still pending, call the check status
    # function of the provider. Update the transaction using the result and return it.
    return _perform_direct_status_check(ledger)


@login_required
def check_deposit_status_view(request, reference: str):
    """
    Explicit endpoint called when user clicks the 'Check Status' button.
    Directly queries the active provider's status API instead of relying on the callback.
    """
    ledger = get_object_or_404(PaymentLedger, reference=reference, user=request.user)
    return _perform_direct_status_check(ledger)


@csrf_exempt
def payment_webhook_view(request, provider_name: str):
    """
    Public webhook receiver for incoming provider payment callbacks (PayHero, KopoKopo, Daraja).
    Parses payload, updates PaymentLedger, and credits user wallet idempotently.
    """
    logger.info("Received payment webhook for provider '%s' (method: %s)", provider_name, request.method)

    # Fast return for health check / verification pings without data
    if request.method == "GET" and not request.GET and not request.body:
        logger.info("Received empty GET ping for provider '%s', returning 200 OK", provider_name)
        return JsonResponse({"status": "ok", "message": f"{provider_name} webhook ready"}, status=200)

    try:
        provider = get_payment_provider(provider_name)
    except Exception as exc:
        logger.error("Unknown provider for webhook '%s': %s", provider_name, exc)
        return JsonResponse({"status": "error", "message": f"Unknown provider: {provider_name}"}, status=400)

    # Extract payload from GET query params, POST raw body, or POST form data
    if request.method == "GET":
        payload_data = request.GET.dict()
    elif request.body:
        payload_data = request.body
    elif request.POST:
        payload_data = request.POST.dict()
    else:
        payload_data = {}

    if not payload_data:
        logger.warning("Empty payload received for provider '%s', returning 200 OK", provider_name)
        return JsonResponse({"status": "ok", "message": "Empty payload received"}, status=200)

    try:
        parsed = provider.parse_webhook(
            raw_body=payload_data,
            headers=dict(request.headers),
        )
    except Exception as exc:
        logger.error("Failed to parse webhook body from %s: %s", provider_name, exc, exc_info=True)
        return JsonResponse({"status": "error", "message": "Failed to parse webhook"}, status=400)

    # Find the matching ledger entry
    ledger = None
    if parsed.reference:
        ledger = PaymentLedger.objects.filter(reference=parsed.reference).first()

    if not ledger and parsed.provider_reference:
        ledger = PaymentLedger.objects.filter(provider_reference=parsed.provider_reference).first()

    if not ledger and parsed.reference:
        # Some providers pass provider_reference in the reference field
        ledger = PaymentLedger.objects.filter(provider_reference=parsed.reference).first()

    if not ledger and parsed.provider_reference:
        ledger = PaymentLedger.objects.filter(reference=parsed.provider_reference).first()

    # Deep fallback: check if CheckoutRequestID or reference matches inside raw_response
    if not ledger and parsed.provider_reference:
        ledger = PaymentLedger.objects.filter(raw_response__icontains=parsed.provider_reference).first()

    if not ledger and parsed.reference:
        ledger = PaymentLedger.objects.filter(raw_response__icontains=parsed.reference).first()

    if not ledger:
        logger.warning(
            "Webhook received for unknown transaction ref=%s, provider_ref=%s",
            parsed.reference,
            parsed.provider_reference,
        )
        # Return 200 so the gateway does not keep bombarding retries
        return JsonResponse({"status": "ignored", "message": "Transaction not found"})

    # Process status
    if parsed.status == "paid":
        credited = ledger.mark_as_paid(
            receipt_number=parsed.receipt_number,
            raw_response=parsed.raw_response,
            reason=parsed.reason,
        )
        logger.info(
            "Webhook credited deposit: ref=%s, amount=%s, receipt=%s, already_paid=%s",
            ledger.reference,
            ledger.amount,
            ledger.receipt_number,
            not credited,
        )
    elif parsed.status == "rejected":
        ledger.mark_as_failed(
            reason=parsed.reason or "Payment was rejected",
            raw_response=parsed.raw_response,
        )
        logger.info("Webhook marked deposit failed: ref=%s, reason=%s", ledger.reference, parsed.reason)

    return JsonResponse({"status": "success", "reference": ledger.reference})


@login_required
@require_POST
def initiate_withdrawal_view(request):
    """
    Initiates an M-Pesa withdrawal for the authenticated user.
    Deducts available balance atomically from the user's Wallet and records PaymentLedger transaction.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid request format. JSON expected."}, status=400)

    raw_phone = str(body.get("phone", "")).strip()
    raw_amount = body.get("amount")

    if not raw_phone:
        return JsonResponse({"success": False, "error": "Please enter your M-Pesa phone number for withdrawal."}, status=400)

    if not raw_amount:
        return JsonResponse({"success": False, "error": "Please specify a withdrawal amount."}, status=400)

    min_withdrawal = getattr(settings, "MIN_WITHDRAWAL_AMOUNT", Decimal("50.00"))
    max_withdrawal = getattr(settings, "MAX_WITHDRAWAL_AMOUNT", Decimal("150000.00"))

    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        if amount < min_withdrawal:
            min_str = f"{int(min_withdrawal)}" if min_withdrawal == int(min_withdrawal) else f"{min_withdrawal}"
            return JsonResponse({"success": False, "error": f"Minimum withdrawal amount is {min_str} KES."}, status=400)
        if amount > max_withdrawal:
            max_str = f"{int(max_withdrawal):,}" if max_withdrawal == int(max_withdrawal) else f"{max_withdrawal:,}"
            return JsonResponse({"success": False, "error": f"Maximum withdrawal amount is {max_str} KES."}, status=400)
    except (ValueError, InvalidOperation):
        return JsonResponse({"success": False, "error": "Invalid amount specified."}, status=400)

    clean_phone = _normalize_kenyan_phone(raw_phone)
    if len(clean_phone) != 12 or not clean_phone.startswith("254"):
        return JsonResponse({"success": False, "error": "Please provide a valid Kenyan phone number (e.g. 07XXXXXXXX or 01XXXXXXXX)."}, status=400)

    with transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(
            user=request.user,
            defaults={"balance": Decimal("0.00")}
        )

        if wallet.available_balance < amount:
            return JsonResponse({
                "success": False,
                "error": f"Insufficient wallet balance. You have {wallet.available_balance:.2f} KES available to withdraw."
            }, status=400)

        # Debit wallet atomically
        wallet.debit(amount, description=f"Withdrawal to {clean_phone}")

        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        reference = f"WTH-{timestamp}-{request.user.id}"
        
        is_marketer = bool(getattr(request.user, "is_marketer", False))

        if is_marketer:
            # Marketers are directly marked as paid/completed
            status = PaymentLedger.Status.COMPLETED
            receipt_number = f"MPESA{secrets.token_hex(4).upper()}"
            completed_at = timezone.now()
            message = f"Withdrawal of {amount:.2f} KES to {clean_phone} processed successfully. Funds will reflect in your M-Pesa account shortly."
            send_mapp_withdrawal_notification(request.user.username, amount)
        else:
            # Regular users remain pending until verified by admin in Ops
            status = PaymentLedger.Status.PENDING
            receipt_number = ""
            completed_at = None
            message = f"Withdrawal request of {amount:.2f} KES to {clean_phone} submitted successfully. It is pending admin verification."

        ledger = PaymentLedger.objects.create(
            user=request.user,
            wallet=wallet,
            transaction_type=PaymentLedger.TransactionType.WITHDRAWAL,
            provider="mpesa_b2c",
            reference=reference,
            receipt_number=receipt_number,
            phone=clean_phone,
            amount=amount,
            currency="KES",
            status=status,
            description=f"Withdrawal of {amount:.2f} KES to {clean_phone}" + (" (Direct/Marketer)" if is_marketer else " (Pending Verification)"),
            raw_request={"phone": clean_phone, "amount": str(amount), "is_marketer": is_marketer},
            completed_at=completed_at,
        )

    logger.info("Processed withdrawal for %s (marketer=%s): ref=%s, status=%s, amount=%s, phone=%s", request.user.username, is_marketer, reference, status, amount, clean_phone)        

    return JsonResponse({
        "success": True,
        "status": status,
        "is_marketer": is_marketer,
        "reference": reference,
        "receipt": receipt_number or reference,
        "amount": float(amount),
        "phone": clean_phone,
        "balance": float(wallet.available_balance),
        "message": message,
    })
