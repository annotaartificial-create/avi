from django.contrib import admin
from .models import SiteSetting


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Platform Identity', {
            'fields': ('name', 'logo', 'favicon', 'tagline')
        }),
        ('Contact Information', {
            'fields': ('contact_email', 'contact_phone', 'address')
        }),
        ('Localization & Financials', {
            'fields': ('currency_symbol', 'currency_code', 'copyright_text')
        }),
        ('System Status', {
            'fields': ('is_maintenance_mode', 'updated_at')
        }),
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        # Disallow adding more than one instance
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Disallow deleting the singleton settings
        return False
