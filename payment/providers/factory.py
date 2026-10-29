from __future__ import annotations

from typing import Type

from django.conf import settings

from .base import BasePaymentProvider, PaymentProviderError
from .daraja import DarajaProvider
from .kopokopo import KopoKopoProvider
from .lipalink import LipaLinkProvider
from .payhero import PayHeroProvider

PROVIDER_REGISTRY: dict[str, Type[BasePaymentProvider]] = {
    "kopokopo": KopoKopoProvider,
    "daraja": DarajaProvider,
    "mpesa": DarajaProvider,
    "payhero": PayHeroProvider,
    "lipalink": LipaLinkProvider,
}


def register_payment_provider(name: str, provider_class: Type[BasePaymentProvider]) -> None:
    """Register a new payment provider adapter dynamically."""
    PROVIDER_REGISTRY[name.lower()] = provider_class


def get_payment_provider(provider_name: str | None = None) -> BasePaymentProvider:
    """
    Resolve payment provider instance.

    If provider_name is None, defaults to settings.ACTIVE_PAYMENT_PROVIDER
    (or 'kopokopo' as standard default).
    """
    name = (provider_name or getattr(settings, "ACTIVE_PAYMENT_PROVIDER", "kopokopo")).strip().lower()
    provider_cls = PROVIDER_REGISTRY.get(name)
    if not provider_cls:
        available = ", ".join(PROVIDER_REGISTRY.keys())
        raise PaymentProviderError(
            f"Unknown payment provider '{name}'. Available providers: {available}"
        )
    return provider_cls()
