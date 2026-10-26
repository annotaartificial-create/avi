from django.urls import path
from . import views

app_name = 'main'

urlpatterns = [
    # Primary Landing Page
    path('', views.landing_view, name='landing'),

    # Legal & Compliance Framework Pages
    path('legal/terms/', views.legal_terms_view, name='legal_terms'),
    path('legal/privacy/', views.legal_privacy_view, name='legal_privacy'),
    path('legal/responsible-gaming/', views.legal_responsible_gaming_view, name='legal_responsible_gaming'),
    path('legal/rules/', views.legal_rules_view, name='legal_rules'),
    path('legal/aml-kyc/', views.legal_aml_view, name='legal_aml'),
]
