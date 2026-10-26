from django.contrib import admin
from .models import Wallet, PaymentLedger


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'locked_balance', 'available_balance', 'currency', 'is_active', 'updated_at')
    search_fields = ('user__username', 'user__email')
    list_filter = ('is_active', 'currency')
    readonly_fields = ('created_at', 'updated_at', 'available_balance')

    def available_balance(self, obj):
        return f"{obj.available_balance:.2f} {obj.currency}"
    available_balance.short_description = "Available"


@admin.register(PaymentLedger)
class PaymentLedgerAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'user', 'transaction_type', 'amount', 'currency',
        'provider', 'receipt_number', 'status', 'created_at'
    )
    list_filter = ('transaction_type', 'status', 'provider', 'currency')
    search_fields = ('reference', 'provider_reference', 'receipt_number', 'phone', 'user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    ordering = ('-created_at',)
