from django.db import models
from django.utils.translation import gettext_lazy as _


class SiteSetting(models.Model):
    """
    Singleton model holding global site-wide constants and contact details.
    Only one instance exists (pk=1).
    """
    name = models.CharField(
        _('Site Name'),
        max_length=100,
        default='Avingine',
        help_text=_('Public name of the project/platform')
    )
    logo = models.FileField(
        _('Site Logo'),
        upload_to='site/logos/',
        blank=True,
        null=True,
        help_text=_('Upload logo file (SVG, PNG, WebP). Used across all site headers.')
    )
    favicon = models.FileField(
        _('Site Favicon'),
        upload_to='site/favicons/',
        blank=True,
        null=True,
        help_text=_('Upload browser favicon (.ico, .png, .svg).')
    )
    tagline = models.CharField(
        _('Tagline'),
        max_length=255,
        default='High-Frequency Market & Execution Engine',
        blank=True
    )
    contact_email = models.EmailField(
        _('Contact Email'),
        default='support@avingine.com',
        help_text=_('Primary email for support and notifications')
    )
    contact_phone = models.CharField(
        _('Contact Phone'),
        max_length=50,
        blank=True,
        default='+1 (555) 019-2834',
        help_text=_('Customer or operations contact phone')
    )
    address = models.CharField(
        _('Physical / Legal Address'),
        max_length=255,
        blank=True,
        default=''
    )
    currency_symbol = models.CharField(
        _('Currency Symbol'),
        max_length=5,
        default='$',
        help_text=_('Default currency symbol for display (e.g. $, KES)')
    )
    currency_code = models.CharField(
        _('Currency Code'),
        max_length=10,
        default='USD',
        help_text=_('ISO currency code (e.g. USD, KES)')
    )
    copyright_text = models.CharField(
        _('Copyright Text'),
        max_length=255,
        blank=True,
        default='Avingine Systems. All rights reserved.'
    )
    is_maintenance_mode = models.BooleanField(
        _('Maintenance Mode'),
        default=False,
        help_text=_('Flag to toggle maintenance mode on marketing or engine features')
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Site Setting')
        verbose_name_plural = _('Site Settings')

    def save(self, *args, **kwargs):
        # Force singleton to always use primary key 1
        self.pk = 1
        if SiteSetting.objects.filter(pk=1).exists():
            kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion of the singleton instance
        pass

    @classmethod
    def load(cls):
        """
        Retrieves the single SiteSetting instance, or creates it with defaults if missing.
        """
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'name': 'Avingine',
                'tagline': 'High-Frequency Market & Execution Engine',
                'contact_email': 'support@avingine.com',
                'contact_phone': '+1 (555) 019-2834',
                'currency_symbol': '$',
                'currency_code': 'USD',
                'copyright_text': 'Avingine Systems. All rights reserved.',
            }
        )
        return obj

    def __str__(self):
        return f"{self.name} Settings"
