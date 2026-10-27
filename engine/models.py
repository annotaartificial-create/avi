import math
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class GameConfig(models.Model):
    """
    Singleton configuration for the Avingine crash game engine.
    Controls house edge, round timings, stake limits, and bot generation.
    """
    house_edge = models.DecimalField(
        _('house edge'),
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0400'),
        help_text=_('House edge fraction (0.0400 = 4% house edge, 96% RTP)')
    )
    instant_crash_rate = models.DecimalField(
        _('instant crash rate'),
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0400'),
        help_text=_('Probability of an instant crash at 1.00x where house claims 100% of stakes')
    )
    betting_countdown_seconds = models.PositiveIntegerField(
        _('betting countdown (seconds)'),
        default=5,
        help_text=_('Duration of betting phase before takeoff')
    )
    crashed_pause_seconds = models.PositiveIntegerField(
        _('crashed pause (seconds)'),
        default=0,
        help_text=_('Duration showing crashed outcome before next round begins (0 = immediate countdown)')
    )
    growth_rate_k = models.FloatField(
        _('flight growth coefficient (k)'),
        default=0.0600,
        help_text=_('Speed curve exponent: Multiplier(t) = e^(k * t)')
    )
    min_bet = models.DecimalField(
        _('minimum bet (KES)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('10.00')
    )
    max_bet = models.DecimalField(
        _('maximum bet (KES)'),
        max_digits=10,
        decimal_places=2,
        default=Decimal('50000.00')
    )
    max_round_payout = models.DecimalField(
        _('max round liability payout (KES)'),
        max_digits=12,
        decimal_places=2,
        default=Decimal('500000.00'),
        help_text=_('Maximum total payout across all players in a single round')
    )
    bot_bets_enabled = models.BooleanField(
        _('enable simulated bot bets'),
        default=True,
        help_text=_('Simulate realistic player bets on the live board for vibrant testing')
    )
    min_bot_count = models.PositiveIntegerField(
        _('min bots per round'),
        default=4
    )
    max_bot_count = models.PositiveIntegerField(
        _('max bots per round'),
        default=9
    )

    class Meta:
        verbose_name = _('game engine configuration')
        verbose_name_plural = _('game engine configuration')

    def __str__(self):
        return f"GameConfig (House Edge: {self.house_edge * 100:.1f}%)"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        if not created and obj.crashed_pause_seconds == 3:
            obj.crashed_pause_seconds = 0
            obj.save(update_fields=['crashed_pause_seconds'])
        return obj


class GameRound(models.Model):
    """
    Represents an individual crash flight round.
    Includes Provably Fair cryptographic seed commitments.
    """
    class Status(models.TextChoices):
        BETTING = 'BETTING', _('Taking Bets')
        FLYING = 'FLYING', _('Flight In Progress')
        CRASHED = 'CRASHED', _('Flight Crashed')

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.BETTING,
        db_index=True
    )
    server_seed = models.CharField(
        max_length=64,
        help_text=_('Secret cryptographic seed; revealed ONLY after crash')
    )
    server_seed_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text=_('SHA-256 hash of server_seed; publicly visible before round')
    )
    client_seed = models.CharField(
        max_length=64,
        help_text=_('Public client seed / round identifier')
    )
    crash_multiplier = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text=_('Target multiplier where flight departs')
    )
    scheduled_start_time = models.DateTimeField(
        db_index=True,
        help_text=_('Exact timestamp when betting ends and flight takes off')
    )
    flight_duration_seconds = models.FloatField(
        help_text=_('Calculated seconds of flight from 1.00x until crash_multiplier')
    )
    crashed_at = models.DateTimeField(
        null=True,
        blank=True
    )
    total_staked = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_payout = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('game round')
        verbose_name_plural = _('game rounds')
        ordering = ['-id']

    def __str__(self):
        return f"Round #{self.id} [{self.status}] Target: {self.crash_multiplier}x"

    @property
    def is_betting(self):
        return self.status == self.Status.BETTING

    @property
    def is_flying(self):
        return self.status == self.Status.FLYING

    @property
    def is_crashed(self):
        return self.status == self.Status.CRASHED

    def get_current_multiplier(self, now=None, growth_k=0.06):
        """
        Calculates the exact multiplier at this moment based on server elapsed time.
        Multiplier(t) = e^(k * t)
        """
        if self.is_betting:
            return Decimal('1.00')
        if self.is_crashed:
            return self.crash_multiplier

        if now is None:
            now = timezone.now()

        elapsed = max(0.0, (now - self.scheduled_start_time).total_seconds())
        if elapsed >= self.flight_duration_seconds:
            return self.crash_multiplier

        current_val = math.exp(growth_k * elapsed)
        # Cap at crash_multiplier
        multiplier = min(float(self.crash_multiplier), current_val)
        return Decimal(f"{multiplier:.2f}")


class Bet(models.Model):
    """
    Represents a player (or simulated bot) stake placed on a GameRound.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending Takeoff')
        PLAYING = 'PLAYING', _('In Flight')
        CASHED_OUT = 'CASHED_OUT', _('Cashed Out (Won)')
        CRASHED = 'CRASHED', _('Crashed (Lost)')

    round = models.ForeignKey(
        GameRound,
        on_delete=models.CASCADE,
        related_name='bets',
        db_index=True
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bets',
        db_index=True
    )
    is_bot = models.BooleanField(default=False, db_index=True)
    player_name = models.CharField(max_length=100)
    stake = models.DecimalField(max_digits=12, decimal_places=2)
    auto_cashout = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Optional multiplier target to automatically cash out')
    )
    cashout_multiplier = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    payout = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    cashed_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('bet')
        verbose_name_plural = _('bets')
        ordering = ['-created_at']

    def __str__(self):
        return f"Bet #{self.id} by {self.player_name}: {self.stake} KES [{self.status}]"
