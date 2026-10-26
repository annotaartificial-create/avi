from django.shortcuts import render
from main.models import SiteSetting


def landing_view(request):
    """
    Renders the primary marketing & landing page for Avingine.
    Showcases real-time tick engine, active live markets, payment rails, and onboarding.
    """
    site_settings = SiteSetting.load()
    return render(request, 'main/landing.html', {
        'site_settings': site_settings
    })


def legal_terms_view(request):
    """
    Renders the Terms of Service legal agreement.
    """
    return render(request, 'legal/terms.html', {
        'active_legal_tab': 'terms'
    })


def legal_privacy_view(request):
    """
    Renders the Privacy & Data Protection Policy.
    """
    return render(request, 'legal/privacy.html', {
        'active_legal_tab': 'privacy'
    })


def legal_responsible_gaming_view(request):
    """
    Renders the Responsible Gaming & Player Protection Guidelines.
    """
    return render(request, 'legal/responsible_gaming.html', {
        'active_legal_tab': 'responsible_gaming'
    })


def legal_rules_view(request):
    """
    Renders the Betting & Tick Trading Technical Rules.
    """
    return render(request, 'legal/rules.html', {
        'active_legal_tab': 'rules'
    })


def legal_aml_view(request):
    """
    Renders the Anti-Money Laundering & KYC Compliance Framework.
    """
    return render(request, 'legal/aml.html', {
        'active_legal_tab': 'aml'
    })
