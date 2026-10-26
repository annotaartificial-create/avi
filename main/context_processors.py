from decimal import Decimal
from django.conf import settings
from .models import SiteSetting


def site_settings(request):
    """
    Exposes the singleton site settings instance to all templates globally.
    Usage: {{ site_settings.name }}, {{ site_settings.contact_email }}, etc.
    """
    try:
        settings_obj = SiteSetting.load()
    except Exception:
        # Fallback if database or table is not yet migrated
        class DummySettings:
            name = 'Avingine'
            logo = None
            favicon = None
            tagline = 'High-Frequency Market & Execution Engine'
            contact_email = 'support@avingine.com'
            contact_phone = '+1 (555) 019-2834'
            currency_symbol = '$'
            currency_code = 'USD'
            copyright_text = 'Avingine Systems. All rights reserved.'
            is_maintenance_mode = False
        settings_obj = DummySettings()

    import os
    min_env = os.getenv('MIN_DEPOSIT_AMOUNT', '').strip()
    if min_env:
        try:
            min_dep = Decimal(min_env)
        except Exception:
            min_dep = getattr(settings, 'MIN_DEPOSIT_AMOUNT', Decimal('10.00'))
    else:
        min_dep = getattr(settings, 'MIN_DEPOSIT_AMOUNT', Decimal('10.00'))
    max_dep = getattr(settings, 'MAX_DEPOSIT_AMOUNT', Decimal('150000.00'))

    return {
        'site_settings': settings_obj,
        'min_deposit_amount': min_dep,
        'max_deposit_amount': max_dep,
    }
