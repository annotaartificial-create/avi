from django.urls import path
from . import views

app_name = 'ops'

urlpatterns = [
    # Dashboard Overview
    path('', views.dashboard_view, name='dashboard'),

    # Marketer Daily Completed Deposits
    path('marketer/', views.marketer_daily_deposits_view, name='marketer'),

    # Users Management
    path('users/', views.users_view, name='users'),
    path('users/<int:user_id>/toggle-role/', views.user_toggle_role_view, name='user_toggle_role'),

    # Wallets Management
    path('wallets/', views.wallets_view, name='wallets'),
    path('wallets/<int:wallet_id>/adjust/', views.wallet_adjust_view, name='wallet_adjust'),

    # Payments Ledger & Operations
    path('payments/', views.payments_view, name='payments'),
    path('payments/<int:ledger_id>/sync-deposit/', views.sync_deposit_view, name='sync_deposit'),
    path('payments/<int:ledger_id>/mark-deposit-paid/', views.mark_deposit_paid_view, name='mark_deposit_paid'),
    path('payments/<int:ledger_id>/withdrawal-action/', views.withdrawal_action_view, name='withdrawal_action'),
]
