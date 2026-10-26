import secrets
import string
from datetime import timedelta
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """
    Custom user manager where email is the unique identifier
    for authentication instead of usernames.
    """
    def generate_unique_username(self, email):
        base_username = email.split('@')[0]
        # Clean username to only alphanumeric and underscores
        clean_base = "".join(c for c in base_username if c.isalnum() or c in ('_', '-')) or 'trader'
        username = clean_base
        counter = 1
        while self.model.objects.filter(username=username).exists():
            random_suffix = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
            username = f"{clean_base}_{random_suffix}"
            counter += 1
            if counter > 10:
                username = f"{clean_base}_{secrets.token_hex(3)}"
                break
        return username

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('The Email must be set'))
        email = self.normalize_email(email)
        
        if not extra_fields.get('username'):
            extra_fields['username'] = self.generate_unique_username(email)
            
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_ops', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model where email is the primary login credential.
    Usernames are auto-generated from email.
    """
    email = models.EmailField(_('email address'), unique=True, db_index=True)
    username = models.CharField(_('username'), max_length=150, unique=True, blank=True)
    first_name = models.CharField(_('first name'), max_length=150, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    
    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )
    is_ops = models.BooleanField(
        _('ops status'),
        default=False,
        help_text=_('Designates whether the user can access the Ops management portal.'),
    )
    is_marketer = models.BooleanField(
        _('marketer status'),
        default=False,
        help_text=_('Designates whether the user is a marketer/affiliate.'),
    )
    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    balance = models.DecimalField(
        _('wallet balance'),
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text=_('Player available balance in KES')
    )
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        ordering = ['-date_joined']

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if not self.username and self.email:
            self.username = User.objects.generate_unique_username(self.email)
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        if self.first_name:
            return f"{self.first_name} {self.last_name}".strip()
        return self.username or self.email.split('@')[0]

    @property
    def wallet_instance(self):
        """Returns the user's single wallet, ensuring it is created if not already present."""
        try:
            return self.wallet
        except Exception:
            from payment.models import Wallet
            wallet, _ = Wallet.objects.get_or_create(user=self, defaults={'balance': Decimal('0.00')})
            return wallet


class PasswordResetCode(models.Model):
    """
    Stores 6-digit verification codes for password reset.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_codes'
    )
    code = models.CharField(max_length=6, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('password reset code')
        verbose_name_plural = _('password reset codes')
        ordering = ['-created_at']

    def __str__(self):
        return f"Reset code for {self.user.email} ({self.code})"

    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at

    @classmethod
    def generate_code_for_user(cls, user, validity_minutes=15):
        # Invalidate old active codes
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        
        # 6-digit numeric code
        code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = timezone.now() + timedelta(minutes=validity_minutes)
        return cls.objects.create(user=user, code=code, expires_at=expires_at)
