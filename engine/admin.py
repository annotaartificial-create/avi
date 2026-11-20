from django.contrib import admin
from .models import GameConfig, GameRound, Bet


@admin.register(GameConfig)
class GameConfigAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'house_edge', 'instant_crash_rate', 'betting_countdown_seconds',
        'crashed_pause_seconds', 'growth_rate_k', 'min_bet', 'max_bet', 'bot_bets_enabled'
    )

    def has_add_permission(self, request):
        return not GameConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GameRound)
class GameRoundAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'status', 'crash_multiplier', 'flight_duration_seconds',
        'total_staked', 'total_payout', 'scheduled_start_time', 'crashed_at', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'server_seed_hash', 'client_seed')
    readonly_fields = ('created_at', 'crashed_at')
    ordering = ('-id',)


@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'round', 'player_name', 'user', 'is_bot', 'stake',
        'auto_cashout', 'cashout_multiplier', 'payout', 'status', 'created_at'
    )
    list_filter = ('status', 'is_bot', 'created_at')
    search_fields = ('player_name', 'user__email', 'user__username', 'round__id')
    readonly_fields = ('created_at', 'cashed_out_at')
    ordering = ('-created_at',)
