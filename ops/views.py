import json
import logging
import secrets
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from acc.models import User
from payment.models import PaymentLedger, Wallet
from payment.views import _perform_direct_status_check
from .decorators import ops_required, ops_or_marketer_required

logger = logging.getLogger(__name__)


# ==============================================================================
# DASHBOARD OVERVIEW
# ==============================================================================

@ops_or_marketer_required
def dashboard_view(request):
    """
    Main Ops overview dashboard showing key metrics, pending action items,
    and recent activity.
    """
    is_ops_staff = bool(getattr(request.user, 'is_ops', False) or request.user.is_superuser or request.user.is_staff)
    is_marketer_only = bool(getattr(request.user, 'is_marketer', False) and not is_ops_staff)

    if is_marketer_only:
        return redirect('ops:marketer')

    # Global User & Wallet metrics (Ops staff only)
    total_users = User.objects.count()
    marketers_count = User.objects.filter(is_marketer=True).count()
    ops_staff_count = User.objects.filter(is_ops=True).count()

    wallets_agg = Wallet.objects.aggregate(
        total_balance=models.Sum('balance'),
        total_locked=models.Sum('locked_balance'),
    )
    total_balance = wallets_agg.get('total_balance') or Decimal('0.00')
    total_locked = wallets_agg.get('total_locked') or Decimal('0.00')
    total_available = max(Decimal('0.00'), total_balance - total_locked)

    # Payment statistics
    pending_deposits_qs = PaymentLedger.objects.filter(
        transaction_type=PaymentLedger.TransactionType.DEPOSIT,
        status=PaymentLedger.Status.PENDING
    )
    pending_deposits_count = pending_deposits_qs.count()
    pending_deposits_sum = pending_deposits_qs.aggregate(s=models.Sum('amount'))['s'] or Decimal('0.00')

    pending_withdrawals_qs = PaymentLedger.objects.filter(
        transaction_type=PaymentLedger.TransactionType.WITHDRAWAL,
        status=PaymentLedger.Status.PENDING
    )
    pending_withdrawals_count = pending_withdrawals_qs.count()
    pending_withdrawals_sum = pending_withdrawals_qs.aggregate(s=models.Sum('amount'))['s'] or Decimal('0.00')

    completed_deposits_sum = PaymentLedger.objects.filter(
        transaction_type=PaymentLedger.TransactionType.DEPOSIT,
        status=PaymentLedger.Status.COMPLETED
    ).aggregate(s=models.Sum('amount'))['s'] or Decimal('0.00')

    completed_withdrawals_sum = PaymentLedger.objects.filter(
        transaction_type=PaymentLedger.TransactionType.WITHDRAWAL,
        status=PaymentLedger.Status.COMPLETED
    ).aggregate(s=models.Sum('amount'))['s'] or Decimal('0.00')

    # Action Items: Pending withdrawals needing verification
    action_withdrawals = pending_withdrawals_qs.select_related('user', 'wallet').order_by('-created_at')[:6]

    # Action Items: Pending deposits that can be synced
    action_deposits = pending_deposits_qs.select_related('user', 'wallet').order_by('-created_at')[:6]

    # Recent completed activity
    recent_transactions = PaymentLedger.objects.select_related('user').order_by('-created_at')[:10]

    context = {
        'page_title': 'Ops Overview',
        'is_ops_staff': is_ops_staff,
        'is_marketer_only': is_marketer_only,
        'total_users': total_users,
        'marketers_count': marketers_count,
        'ops_staff_count': ops_staff_count,
        'total_balance': total_balance,
        'total_locked': total_locked,
        'total_available': total_available,
        'pending_deposits_count': pending_deposits_count,
        'pending_deposits_sum': pending_deposits_sum,
        'pending_withdrawals_count': pending_withdrawals_count,
        'pending_withdrawals_sum': pending_withdrawals_sum,
        'completed_deposits_sum': completed_deposits_sum,
        'completed_withdrawals_sum': completed_withdrawals_sum,
        'action_withdrawals': action_withdrawals,
        'action_deposits': action_deposits,
        'recent_transactions': recent_transactions,
    }
    return render(request, 'ops/dashboard.html', context)


# ==============================================================================
# MARKETER DAILY DEPOSITS
# ==============================================================================

@ops_or_marketer_required
def marketer_daily_deposits_view(request):
    """
    Shows completed (paid) deposits for the day (or a selected date) for marketers and Ops staff.
    """
    from datetime import datetime

    is_ops_staff = bool(getattr(request.user, 'is_ops', False) or request.user.is_superuser or request.user.is_staff)
    is_marketer = bool(getattr(request.user, 'is_marketer', False))

    today = timezone.localdate()
    date_str = request.GET.get('date', '').strip()
    selected_date = today

    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = today

    query = request.GET.get('q', '').strip()

    # Query completed (paid) deposits for the selected date
    deposits_qs = PaymentLedger.objects.filter(
        transaction_type=PaymentLedger.TransactionType.DEPOSIT,
        status=PaymentLedger.Status.COMPLETED,
    ).filter(
        models.Q(completed_at__date=selected_date)
        | (models.Q(completed_at__isnull=True) & models.Q(created_at__date=selected_date))
    ).select_related('user').order_by('-completed_at', '-created_at')

    # Aggregates for the day (computed before search filter for true daily KPI cards)
    total_day_amount = deposits_qs.aggregate(s=models.Sum('amount'))['s'] or Decimal('0.00')
    total_day_count = deposits_qs.count()
    unique_depositors = deposits_qs.values('user_id').distinct().count()
    avg_deposit = (total_day_amount / total_day_count) if total_day_count > 0 else Decimal('0.00')

    # Apply search filter if provided
    if query:
        deposits_qs = deposits_qs.filter(
            models.Q(receipt_number__icontains=query)
            | models.Q(phone__icontains=query)
            | models.Q(reference__icontains=query)
            | models.Q(provider_reference__icontains=query)
            | models.Q(user__email__icontains=query)
            | models.Q(user__username__icontains=query)
        )

    paginator = Paginator(deposits_qs, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Marketer Daily Deposits',
        'is_ops_staff': is_ops_staff,
        'is_marketer': is_marketer,
        'selected_date': selected_date,
        'selected_date_str': selected_date.strftime('%Y-%m-%d'),
        'today': today,
        'is_today': (selected_date == today),
        'query': query,
        'page_obj': page_obj,
        'total_count': paginator.count,
        'total_day_amount': total_day_amount,
        'total_day_count': total_day_count,
        'unique_depositors': unique_depositors,
        'avg_deposit': avg_deposit,
    }
    return render(request, 'ops/marketer.html', context)


# ==============================================================================
# USERS MANAGEMENT
# ==============================================================================

@ops_required
def users_view(request):
    """
    Search, filter, and view users with instant toggles for is_marketer and is_ops roles.
    """
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', 'all').lower()

    users_qs = User.objects.select_related('wallet').order_by('-date_joined')

    if query:
        users_qs = users_qs.filter(
            models.Q(email__icontains=query)
            | models.Q(username__icontains=query)
            | models.Q(first_name__icontains=query)
            | models.Q(last_name__icontains=query)
            | models.Q(id__iexact=query)
        )

    if role_filter == 'marketer':
        users_qs = users_qs.filter(is_marketer=True)
    elif role_filter == 'ops':
        users_qs = users_qs.filter(is_ops=True)
    elif role_filter == 'staff':
        users_qs = users_qs.filter(is_staff=True)
    elif role_filter == 'regular':
        users_qs = users_qs.filter(is_marketer=False, is_ops=False, is_staff=False, is_superuser=False)

    paginator = Paginator(users_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Users Management',
        'page_obj': page_obj,
        'query': query,
        'role_filter': role_filter,
        'total_count': paginator.count,
    }
    return render(request, 'ops/users.html', context)


@ops_required
@require_POST
def user_toggle_role_view(request, user_id: int):
    """
    Toggles is_ops or is_marketer flag for a specific user.
    Supports both AJAX JSON requests and standard form submissions.
    """
    target_user = get_object_or_404(User, id=user_id)

    # Parse role parameter
    role = request.POST.get('role') or ""
    if not role and request.body:
        try:
            body = json.loads(request.body)
            role = body.get('role', '')
        except Exception:
            pass

    role = role.strip().lower()

    if role not in ('is_ops', 'is_marketer'):
        return JsonResponse({'success': False, 'error': 'Invalid role specified.'}, status=400)

    # Protect against self-lockout from Ops if this is the user's own account
    if role == 'is_ops' and target_user == request.user and not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'error': 'You cannot revoke your own Ops staff access.'
        }, status=400)

    current_val = getattr(target_user, role)
    new_val = not current_val
    setattr(target_user, role, new_val)
    target_user.save(update_fields=[role])

    logger.info("Admin %s toggled %s=%s for user %s (id=%d)", request.user.email, role, new_val, target_user.email, target_user.id)

    msg = f"Updated {target_user.email}: {role} is now {'ENABLED' if new_val else 'DISABLED'}."

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'user_id': target_user.id,
            'role': role,
            'new_value': new_val,
            'is_ops': target_user.is_ops,
            'is_marketer': target_user.is_marketer,
            'message': msg,
        })

    messages.success(request, msg)
    return redirect(request.META.get('HTTP_REFERER') or 'ops:users')


# ==============================================================================
# WALLETS MANAGEMENT
# ==============================================================================

@ops_required
def wallets_view(request):
    """
    List user wallets, inspect balances, and adjust funds.
    """
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('filter', 'all').lower()

    wallets_qs = Wallet.objects.select_related('user').order_by('-balance')

    if query:
        wallets_qs = wallets_qs.filter(
            models.Q(user__email__icontains=query)
            | models.Q(user__username__icontains=query)
            | models.Q(user__id__iexact=query)
        )

    if status_filter == 'positive':
        wallets_qs = wallets_qs.filter(balance__gt=0)
    elif status_filter == 'zero':
        wallets_qs = wallets_qs.filter(balance=0)
    elif status_filter == 'locked':
        wallets_qs = wallets_qs.filter(locked_balance__gt=0)

    paginator = Paginator(wallets_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Wallets Management',
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'total_count': paginator.count,
    }
    return render(request, 'ops/wallets.html', context)


@ops_required
@require_POST
def wallet_adjust_view(request, wallet_id: int):
    """
    Adjusts a user's wallet balance (Set, Credit, or Debit) with an audit reason.
    """
    wallet = get_object_or_404(Wallet.objects.select_for_update(), id=wallet_id)

    # Read params
    is_json = request.content_type == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if is_json and request.body:
        try:
            data = json.loads(request.body)
        except Exception:
            data = {}
    else:
        data = request.POST

    action_type = str(data.get('action_type', '')).strip().lower()
    raw_amount = data.get('amount')
    reason = str(data.get('reason', '')).strip()

    if action_type not in ('set', 'credit', 'debit'):
        err = "Invalid adjustment action type. Choose 'set', 'credit', or 'debit'."
        return JsonResponse({'success': False, 'error': err}, status=400) if is_json else _wallet_err(request, err)

    try:
        amount = Decimal(str(raw_amount)).quantize(Decimal('0.01'))
        if amount < 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        err = "Please enter a valid positive numerical amount."
        return JsonResponse({'success': False, 'error': err}, status=400) if is_json else _wallet_err(request, err)

    if not reason:
        reason = f"Manual adjustment by {request.user.email}"
    else:
        reason = f"{reason} (by {request.user.email})"

    with transaction.atomic():
        old_balance = wallet.balance
        if action_type == 'set':
            wallet.balance = amount
            wallet.save(update_fields=['balance', 'updated_at'])
            wallet.sync_to_user()
            msg = f"Wallet balance for {wallet.user.email} updated from {old_balance:.2f} KES to {wallet.balance:.2f} KES."

        elif action_type == 'credit':
            if amount == 0:
                err = "Credit amount must be greater than zero."
                return JsonResponse({'success': False, 'error': err}, status=400) if is_json else _wallet_err(request, err)
            wallet.credit(amount, description=reason)
            msg = f"Credited {amount:.2f} KES to {wallet.user.email}. New balance: {wallet.balance:.2f} KES."

        elif action_type == 'debit':
            if amount == 0:
                err = "Debit amount must be greater than zero."
                return JsonResponse({'success': False, 'error': err}, status=400) if is_json else _wallet_err(request, err)
            if wallet.available_balance < amount:
                err = f"Cannot debit {amount:.2f} KES. User only has {wallet.available_balance:.2f} KES available."
                return JsonResponse({'success': False, 'error': err}, status=400) if is_json else _wallet_err(request, err)
            wallet.debit(amount, description=reason)
            msg = f"Debited {amount:.2f} KES from {wallet.user.email}. New balance: {wallet.balance:.2f} KES."

        logger.info("Admin %s adjusted wallet #%d (%s): action=%s, amount=%s, reason=%s", request.user.email, wallet.id, wallet.user.email, action_type, amount, reason)

    if is_json:
        return JsonResponse({
            'success': True,
            'wallet_id': wallet.id,
            'balance': float(wallet.balance),
            'locked_balance': float(wallet.locked_balance),
            'available_balance': float(wallet.available_balance),
            'message': msg,
        })

    messages.success(request, msg)
    return redirect('ops:wallets')


def _wallet_err(request, message: str):
    messages.error(request, message)
    return redirect('ops:wallets')


# ==============================================================================
# PAYMENTS LEDGER & OPERATIONS
# ==============================================================================

@ops_or_marketer_required
def payments_view(request):
    """
    Unified payment transaction ledger for deposits and withdrawals with filtering,
    instant status queries, and manual processing actions.
    """
    is_ops_staff = bool(getattr(request.user, 'is_ops', False) or request.user.is_superuser or request.user.is_staff)

    query = request.GET.get('q', '').strip()
    tx_type = request.GET.get('type', 'ALL').upper()
    status_filter = request.GET.get('status', 'ALL').upper()

    ledger_qs = PaymentLedger.objects.select_related('user', 'wallet').order_by('-created_at')

    # If marketer only (not ops staff), only show marketer's own records
    if not is_ops_staff and getattr(request.user, 'is_marketer', False):
        ledger_qs = ledger_qs.filter(user=request.user)

    if query:
        ledger_qs = ledger_qs.filter(
            models.Q(reference__icontains=query)
            | models.Q(provider_reference__icontains=query)
            | models.Q(receipt_number__icontains=query)
            | models.Q(phone__icontains=query)
            | models.Q(user__email__icontains=query)
            | models.Q(user__username__icontains=query)
        )

    if tx_type in ('DEPOSIT', 'WITHDRAWAL'):
        ledger_qs = ledger_qs.filter(transaction_type=tx_type)

    if status_filter in ('PENDING', 'COMPLETED', 'FAILED', 'CANCELLED'):
        ledger_qs = ledger_qs.filter(status=status_filter)

    paginator = Paginator(ledger_qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': 'Payments Ledger',
        'is_ops_staff': is_ops_staff,
        'page_obj': page_obj,
        'query': query,
        'tx_type': tx_type,
        'status_filter': status_filter,
        'total_count': paginator.count,
    }
    return render(request, 'ops/payments.html', context)


@ops_required
@require_POST
def sync_deposit_view(request, ledger_id: int):
    """
    Syncs / verifies a pending deposit directly with the gateway provider.
    Credits the user's wallet automatically if confirmed paid.
    """
    ledger = get_object_or_404(
        PaymentLedger.objects.select_related('wallet', 'user'),
        id=ledger_id,
        transaction_type=PaymentLedger.TransactionType.DEPOSIT
    )

    # Perform direct gateway query
    response = _perform_direct_status_check(ledger)
    
    # Reload from DB to ensure freshest state
    ledger.refresh_from_db()
    
    logger.info("Admin %s synced deposit #%d (ref=%s): status=%s", request.user.email, ledger.id, ledger.reference, ledger.status)

    return JsonResponse({
        'success': True,
        'ledger_id': ledger.id,
        'reference': ledger.reference,
        'status': ledger.status,
        'receipt_number': ledger.receipt_number,
        'wallet_balance': float(ledger.wallet.available_balance),
        'message': f"Sync complete. Transaction status is {ledger.status}."
    })


@ops_required
@require_POST
def mark_deposit_paid_view(request, ledger_id: int):
    """
    Manually marks a pending deposit as COMPLETED (paid) by an Ops admin
    and credits the user's wallet atomically.
    """
    ledger = get_object_or_404(
        PaymentLedger.objects.select_related('wallet', 'user'),
        id=ledger_id,
        transaction_type=PaymentLedger.TransactionType.DEPOSIT
    )

    if ledger.status == PaymentLedger.Status.COMPLETED:
        return JsonResponse({'success': False, 'error': 'Deposit is already marked as completed.'}, status=400)

    # Read receipt number & note
    is_json = request.content_type == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if is_json and request.body:
        try:
            data = json.loads(request.body)
        except Exception:
            data = {}
    else:
        data = request.POST

    receipt_number = str(data.get('receipt_number', '')).strip()
    if not receipt_number:
        receipt_number = f"MANUAL{secrets.token_hex(4).upper()}"

    reason = str(data.get('reason', '')).strip() or f"Manually verified by {request.user.email}"

    credited = ledger.mark_as_paid(
        receipt_number=receipt_number,
        reason=reason,
    )

    logger.info("Admin %s manually approved deposit #%d (%s) with receipt %s", request.user.email, ledger.id, ledger.reference, receipt_number)

    msg = f"Deposit {ledger.reference} marked as COMPLETED. Credited {ledger.amount:.2f} KES to {ledger.user.email}."

    if is_json:
        return JsonResponse({
            'success': True,
            'ledger_id': ledger.id,
            'status': ledger.status,
            'receipt_number': ledger.receipt_number,
            'wallet_balance': float(ledger.wallet.available_balance),
            'message': msg,
        })

    messages.success(request, msg)
    return redirect('ops:payments')


@ops_required
@require_POST
def withdrawal_action_view(request, ledger_id: int):
    """
    Action endpoint for pending withdrawals:
    - 'approve': Mark as paid (COMPLETED) with receipt number.
    - 'reject': Mark as CANCELLED and refund wallet atomically.
    """
    ledger = get_object_or_404(
        PaymentLedger.objects.select_related('wallet', 'user'),
        id=ledger_id,
        transaction_type=PaymentLedger.TransactionType.WITHDRAWAL
    )

    if ledger.status != PaymentLedger.Status.PENDING:
        return JsonResponse({
            'success': False,
            'error': f'Withdrawal cannot be modified. Current status is {ledger.status}.'
        }, status=400)

    is_json = request.content_type == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if is_json and request.body:
        try:
            data = json.loads(request.body)
        except Exception:
            data = {}
    else:
        data = request.POST

    action = str(data.get('action', '')).strip().lower()
    receipt_number = str(data.get('receipt_number', '')).strip()
    reason = str(data.get('reason', '')).strip()

    if action not in ('approve', 'reject'):
        return JsonResponse({'success': False, 'error': "Invalid action. Choose 'approve' or 'reject'."}, status=400)

    with transaction.atomic():
        locked_ledger = PaymentLedger.objects.select_for_update().get(id=ledger.id)
        if locked_ledger.status != PaymentLedger.Status.PENDING:
            return JsonResponse({'success': False, 'error': 'Withdrawal has already been processed.'}, status=400)

        if action == 'approve':
            if not receipt_number:
                receipt_number = f"MPESA{secrets.token_hex(4).upper()}"
            
            locked_ledger.status = PaymentLedger.Status.COMPLETED
            locked_ledger.receipt_number = receipt_number
            locked_ledger.completed_at = timezone.now()
            if reason:
                locked_ledger.description = f"{locked_ledger.description} - Verified: {reason}"
            locked_ledger.save(update_fields=['status', 'receipt_number', 'completed_at', 'description', 'updated_at'])

            msg = f"Withdrawal {locked_ledger.reference} approved and marked as PAID (Receipt: {receipt_number})."
            logger.info("Admin %s approved withdrawal #%d (%s) receipt=%s", request.user.email, locked_ledger.id, locked_ledger.reference, receipt_number)

        elif action == 'reject':
            rejection_reason = reason or "Withdrawal rejected by administrator"
            locked_ledger.status = PaymentLedger.Status.CANCELLED
            locked_ledger.error_message = f"Rejected by {request.user.email}: {rejection_reason}"
            locked_ledger.save(update_fields=['status', 'error_message', 'updated_at'])

            # Refund wallet atomically since funds were reserved/debited on request creation
            locked_ledger.wallet.credit(
                locked_ledger.amount,
                description=f"Refund for cancelled withdrawal {locked_ledger.reference}"
            )

            msg = f"Withdrawal {locked_ledger.reference} rejected. Refunded {locked_ledger.amount:.2f} KES back to {locked_ledger.user.email}'s wallet."
            logger.info("Admin %s rejected withdrawal #%d (%s), refunded %s KES", request.user.email, locked_ledger.id, locked_ledger.reference, locked_ledger.amount)

    if action == 'approve':
        from payment.views import send_mapp_withdrawal_notification
        send_mapp_withdrawal_notification(locked_ledger.user.username, locked_ledger.amount)

    if is_json:
        return JsonResponse({
            'success': True,
            'ledger_id': locked_ledger.id,
            'status': locked_ledger.status,
            'receipt_number': locked_ledger.receipt_number,
            'wallet_balance': float(locked_ledger.wallet.available_balance),
            'message': msg,
        })

    messages.success(request, msg)
    return redirect('ops:payments')
