from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Wallet(models.Model):
    """
    User Wallet model (1-to-1 relationship with User).
    
    Holds:
    - balance: The total real monetary balance belonging to the user.
    - locked_balance: Balance temporarily locked/reserved for active unsettled stakes.
    - available_balance: balance - locked_balance (funds available for new stakes or withdrawal).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name=_('user'),
    )
    balance = models.DecimalField(
        _('real balance'),
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Total actual balance in KES'),
    )
    locked_balance = models.DecimalField(
        _('locked balance'),
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Balance currently reserved for active in-play stakes'),
    )
    currency = models.CharField(
        _('currency'),
        max_length=10,
        default='KES',
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('wallet')
        verbose_name_plural = _('wallets')

    def __str__(self) -> str:
        return f"Wallet for {self.user.username} ({self.available_balance:.2f} {self.currency} available / {self.balance:.2f} real)"

    @property
    def available_balance(self) -> Decimal:
        """Funds that can be staked or withdrawn."""
        return max(Decimal('0.00'), self.balance - self.locked_balance)

    def sync_to_user(self):
        """Keep user.balance in sync with available_balance for backward compatibility."""
        from acc.models import User
        User.objects.filter(id=self.user_id).update(balance=self.available_balance)

    def can_stake(self, amount: Decimal) -> bool:
        return self.is_active and self.available_balance >= amount

    def lock_funds(self, amount: Decimal) -> bool:
        """
        Locks funds when a stake is placed.
        Deducts from available balance by increasing locked_balance.
        Real balance remains unchanged until the bet is settled.
        """
        if amount <= 0 or not self.can_stake(amount):
            return False
        self.locked_balance += amount
        self.save(update_fields=['locked_balance', 'updated_at'])
        self.sync_to_user()
        return True

    def unlock_funds(self, amount: Decimal) -> bool:
        """Unlocks funds (e.g. if a round is cancelled or refunded)."""
        self.locked_balance = max(Decimal('0.00'), self.locked_balance - amount)
        self.save(update_fields=['locked_balance', 'updated_at'])
        self.sync_to_user()
        return True

    def settle_loss(self, stake: Decimal):
        """
        Settles a lost bet.
        Reduces both locked_balance and real balance.
        """
        self.locked_balance = max(Decimal('0.00'), self.locked_balance - stake)
        self.balance = max(Decimal('0.00'), self.balance - stake)
        self.save(update_fields=['balance', 'locked_balance', 'updated_at'])
        self.sync_to_user()

    def settle_win(self, stake: Decimal, payout: Decimal):
        """
        Settles a winning bet (cashout).
        Releases locked stake, and adds net profit to real balance.
        """
        self.locked_balance = max(Decimal('0.00'), self.locked_balance - stake)
        self.balance = self.balance - stake + payout
        self.save(update_fields=['balance', 'locked_balance', 'updated_at'])
        self.sync_to_user()

    def credit(self, amount: Decimal, description: str = ""):
        """
        Credits real balance (e.g. successful deposit).
        """
        if amount <= 0:
            raise ValueError("Credit amount must be positive.")
        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])
        self.sync_to_user()

    def debit(self, amount: Decimal, description: str = ""):
        """
        Debits real balance (e.g. withdrawal).
        """
        if amount <= 0:
            raise ValueError("Debit amount must be positive.")
        if self.available_balance < amount:
            raise ValueError("Insufficient available balance.")
        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])
        self.sync_to_user()


class PaymentLedger(models.Model):
    """
    Single source of truth for all deposits and withdrawals.
    Tracks transaction kind, provider, references, statuses, and audit trail.
    """
    class TransactionType(models.TextChoices):
        DEPOSIT = 'DEPOSIT', _('Deposit')
        WITHDRAWAL = 'WITHDRAWAL', _('Withdrawal')

    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        COMPLETED = 'COMPLETED', _('Completed')
        FAILED = 'FAILED', _('Failed')
        CANCELLED = 'CANCELLED', _('Cancelled')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payment_ledgers',
        verbose_name=_('user'),
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='ledgers',
        verbose_name=_('wallet'),
    )
    transaction_type = models.CharField(
        _('transaction type'),
        max_length=20,
        choices=TransactionType.choices,
        default=TransactionType.DEPOSIT,
        db_index=True,
    )
    provider = models.CharField(
        _('provider'),
        max_length=50,
        default='payhero',
        db_index=True,
        help_text=_('Payment provider adapter used (e.g. payhero, kopokopo, daraja)'),
    )
    reference = models.CharField(
        _('internal reference'),
        max_length=100,
        unique=True,
        db_index=True,
        help_text=_('Unique system transaction identifier (e.g. DEP-...)'),
    )
    provider_reference = models.CharField(
        _('provider reference'),
        max_length=150,
        blank=True,
        db_index=True,
        help_text=_('Reference returned by external payment gateway (e.g. CheckoutRequestID)'),
    )
    receipt_number = models.CharField(
        _('receipt number'),
        max_length=100,
        blank=True,
        db_index=True,
        help_text=_('Official payment receipt (e.g. M-Pesa receipt code)'),
    )
    phone = models.CharField(
        _('phone number'),
        max_length=25,
        blank=True,
        help_text=_('Subscriber phone number used for the transaction'),
    )
    amount = models.DecimalField(
        _('amount'),
        max_digits=12,
        decimal_places=2,
    )
    currency = models.CharField(
        _('currency'),
        max_length=10,
        default='KES',
    )
    status = models.CharField(
        _('status'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    description = models.CharField(
        _('description'),
        max_length=255,
        blank=True,
    )
    error_message = models.TextField(
        _('error message'),
        blank=True,
    )
    raw_request = models.JSONField(
        _('raw request payload'),
        default=dict,
        blank=True,
    )
    raw_response = models.JSONField(
        _('raw response payload'),
        default=dict,
        blank=True,
    )
    metadata = models.JSONField(
        _('metadata'),
        default=dict,
        blank=True,
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    completed_at = models.DateTimeField(_('completed at'), null=True, blank=True)

    class Meta:
        verbose_name = _('payment ledger')
        verbose_name_plural = _('payment ledgers')
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"[{self.transaction_type}] {self.reference} ({self.amount} {self.currency}) - {self.status}"

    @property
    def is_completed(self) -> bool:
        return self.status == self.Status.COMPLETED

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def is_failed(self) -> bool:
        return self.status in [self.Status.FAILED, self.Status.CANCELLED]

    def mark_as_paid(
        self,
        receipt_number: str = "",
        raw_response: dict | None = None,
        reason: str = "",
    ) -> bool:
        """
        Marks transaction as COMPLETED and credits user wallet atomically.
        Idempotent: if already COMPLETED, does not double-credit.
        """
        with transaction.atomic():
            locked = PaymentLedger.objects.select_for_update().get(id=self.id)
            if locked.status == self.Status.COMPLETED:
                return False  # Already processed

            locked.status = self.Status.COMPLETED
            if receipt_number:
                locked.receipt_number = str(receipt_number).strip()
            if raw_response:
                locked.raw_response = raw_response
            if reason and not locked.description:
                locked.description = reason
            locked.completed_at = timezone.now()
            locked.save(update_fields=[
                'status', 'receipt_number', 'raw_response', 'description', 'completed_at', 'updated_at'
            ])

            # Credit user wallet if deposit
            if locked.transaction_type == self.TransactionType.DEPOSIT:
                locked.wallet.credit(locked.amount, description=f"Deposit via {locked.provider} ({locked.reference})")

            # Update in-memory fields on self
            self.status = locked.status
            self.receipt_number = locked.receipt_number
            self.completed_at = locked.completed_at
            return True

    def mark_as_failed(self, reason: str = "", raw_response: dict | None = None) -> bool:
        """
        Marks transaction as FAILED.
        """
        with transaction.atomic():
            locked = PaymentLedger.objects.select_for_update().get(id=self.id)
            if locked.status == self.Status.COMPLETED:
                return False  # Never fail an already completed payment

            locked.status = self.Status.FAILED
            if reason:
                locked.error_message = reason
            if raw_response:
                locked.raw_response = raw_response
            locked.save(update_fields=['status', 'error_message', 'raw_response', 'updated_at'])

            self.status = locked.status
            self.error_message = locked.error_message
            return True
