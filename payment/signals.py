from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Wallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_wallet(sender, instance, created, **kwargs):
    """
    Ensure every user has one and only one corresponding Wallet instance upon creation or update.
    The OneToOneField database constraint strictly guarantees that at most one wallet can ever exist per user.
    """
    Wallet.objects.get_or_create(
        user=instance,
        defaults={'balance': Decimal('0.00')}
    )
