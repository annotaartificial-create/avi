from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


class PaymentProviderError(Exception):
    """Base error for third-party payment provider interactions."""

    def __init__(self, message: str, *, code: str | None = None, payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


@dataclass
class DepositInitiateResult:
    """Normalized output from initiate_deposit across all providers."""

    success: bool
    reference: str
    provider_reference: str = ""
    resource_location: str = ""
    message: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransactionStatusResult:
    """Normalized output from querying a deposit transaction."""

    status: str  # "paid", "rejected", "pending"
    provider_reference: str = ""
    receipt_number: str = ""
    reason: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookParseResult:
    """Normalized output from parsing a provider callback / webhook."""

    reference: str
    status: str  # "paid", "rejected", "pending"
    provider_reference: str = ""
    receipt_number: str = ""
    reason: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)


class BasePaymentProvider(ABC):
    """Abstract interface that every payment provider adapter must implement."""

    name: str = "base"

    @abstractmethod
    def initiate_deposit(
        self,
        *,
        reference: str,
        phone: str,
        amount_kes: int,
        amount_usd: Decimal,
        callback_url: str = "",
    ) -> DepositInitiateResult:
        """Send STK push or initiate payment with provider."""
        ...

    @abstractmethod
    def query_deposit(
        self,
        *,
        reference: str = "",
        resource_location: str = "",
        provider_reference: str = "",
    ) -> TransactionStatusResult:
        """Query provider to check if a pending deposit succeeded, failed, or is still pending."""
        ...

    @abstractmethod
    def parse_webhook(
        self,
        *,
        raw_body: bytes | str | dict,
        headers: dict | None = None,
    ) -> WebhookParseResult:
        """Parse raw callback payload from webhook into standardized result."""
        ...
