import random
from typing import Tuple
from decimal import Decimal
from datetime import timedelta
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import GameConfig, GameRound, Bet
from .generator import (
    generate_round_secrets,
    calculate_crash_multiplier,
    multiplier_to_flight_duration,
    flight_duration_to_multiplier
)

BOT_NAMES = [
    "Kev_Nbo", "AlphaPilot", "Mwangi_K", "Wanjiku88", "CryptoJet",
    "Sarah_M", "Flyer99", "TraderTom", "Ochieng_L", "SkyHigh",
    "ApexRider", "Amina_A", "Falcon_254", "JetSetter", "Brian_O",
    "VortexBet", "CaptainKen", "Grace_W", "SpeedyG", "TurboAce",
    "Kip_Fast", "LuckyFlight", "RocketMan", "NairobiKing", "MaasaiAir"
]

STAKE_OPTIONS = [
    Decimal('50.00'), Decimal('100.00'), Decimal('150.00'),
    Decimal('200.00'), Decimal('300.00'), Decimal('500.00'),
    Decimal('1000.00'), Decimal('1500.00'), Decimal('2000.00')
]


class EngineService:
    @staticmethod
    def get_or_advance_current_round() -> GameRound:
        """
        Advances the state machine of the crash game.
        Maintains continuous round loop: BETTING -> FLYING -> CRASHED -> NEXT ROUND.
        Thread-safe execution.
        """
        now = timezone.now()
        config = GameConfig.load()

        # Find latest round
        latest_round = GameRound.objects.order_by('-id').first()

        if not latest_round:
            # First round ever
            return EngineService._create_new_round(config, now)

        # 1. If round is BETTING: check if countdown finished
        if latest_round.is_betting:
            if now >= latest_round.scheduled_start_time:
                with transaction.atomic():
                    round_locked = GameRound.objects.select_for_update().get(id=latest_round.id)
                    if round_locked.is_betting:
                        round_locked.status = GameRound.Status.FLYING
                        round_locked.save(update_fields=['status'])
                        # Move all pending bets to in-play
                        round_locked.bets.filter(status=Bet.Status.PENDING).update(status=Bet.Status.PLAYING)
                return GameRound.objects.get(id=latest_round.id)
            return latest_round

        # 2. If round is FLYING: check if crash time has arrived
        if latest_round.is_flying:
            elapsed = (now - latest_round.scheduled_start_time).total_seconds()
            if elapsed >= latest_round.flight_duration_seconds:
                with transaction.atomic():
                    round_locked = GameRound.objects.select_for_update().get(id=latest_round.id)
                    if round_locked.is_flying:
                        round_locked.status = GameRound.Status.CRASHED
                        round_locked.crashed_at = round_locked.scheduled_start_time + timedelta(
                            seconds=round_locked.flight_duration_seconds
                        )
                        round_locked.save(update_fields=['status', 'crashed_at'])
                        EngineService._settle_crashed_round(round_locked)

                        # If pause duration is 0, start the new round's countdown immediately!
                        if config.crashed_pause_seconds == 0:
                            return EngineService._create_new_round(config, now)

                return GameRound.objects.get(id=latest_round.id)
            return latest_round

        # 3. If round is CRASHED: check if pause duration has elapsed
        if latest_round.is_crashed:
            crashed_time = latest_round.crashed_at or latest_round.created_at
            pause_end = crashed_time + timedelta(seconds=config.crashed_pause_seconds)
            if config.crashed_pause_seconds == 0 or now >= pause_end:
                return EngineService._create_new_round(config, now)
            return latest_round

        return latest_round

    @staticmethod
    def _create_new_round(config: GameConfig, now) -> GameRound:
        """
        Creates a new GameRound with Provably Fair commitment seeds and spawns bots.
        """
        server_seed, server_seed_hash, client_seed = generate_round_secrets()
        crash_multiplier = calculate_crash_multiplier(
            server_seed=server_seed,
            client_seed=client_seed,
            house_edge=config.house_edge,
            instant_crash_rate=config.instant_crash_rate
        )
        duration = multiplier_to_flight_duration(crash_multiplier, growth_k=config.growth_rate_k)
        start_time = now + timedelta(seconds=config.betting_countdown_seconds)

        with transaction.atomic():
            new_round = GameRound.objects.create(
                status=GameRound.Status.BETTING,
                server_seed=server_seed,
                server_seed_hash=server_seed_hash,
                client_seed=client_seed,
                crash_multiplier=crash_multiplier,
                scheduled_start_time=start_time,
                flight_duration_seconds=duration
            )

            # Spawn simulated bot bets for testing
            if config.bot_bets_enabled:
                EngineService._spawn_bot_bets(new_round, config)

        return new_round

    @staticmethod
    def _spawn_bot_bets(game_round: GameRound, config: GameConfig):
        """
        Generates simulated bot bets with realistic stakes and auto-cashout values.
        """
        bot_count = random.randint(config.min_bot_count, config.max_bot_count)
        chosen_names = random.sample(BOT_NAMES, min(bot_count, len(BOT_NAMES)))

        bot_bets = []
        for name in chosen_names:
            stake = random.choice(STAKE_OPTIONS)
            # 60% of bots have an auto-cashout target
            auto_cashout = None
            if random.random() < 0.60:
                # Random cashout between 1.15x and 15.00x
                target = round(random.uniform(1.15, 6.50), 2)
                auto_cashout = Decimal(str(target))

            bot_bets.append(Bet(
                round=game_round,
                is_bot=True,
                player_name=name,
                stake=stake,
                auto_cashout=auto_cashout,
                status=Bet.Status.PENDING
            ))

        Bet.objects.bulk_create(bot_bets)

    @staticmethod
    def _settle_crashed_round(game_round: GameRound):
        """
        Settles all bets when a round crashes.
        Processes auto-cashouts for qualifying bets, marks the rest as lost.
        """
        crash_point = game_round.crash_multiplier

        # Process any pending/playing bets with auto_cashout <= crash_multiplier
        unresolved_bets = game_round.bets.filter(status__in=[Bet.Status.PLAYING, Bet.Status.PENDING])

        for bet in unresolved_bets:
            if bet.auto_cashout and bet.auto_cashout <= crash_point:
                # Successful auto-cashout
                payout = bet.stake * bet.auto_cashout
                bet.status = Bet.Status.CASHED_OUT
                bet.cashout_multiplier = bet.auto_cashout
                bet.payout = payout
                bet.cashed_out_at = game_round.crashed_at
                bet.save(update_fields=['status', 'cashout_multiplier', 'payout', 'cashed_out_at'])

                # Credit real player wallet if not bot
                if bet.user:
                    try:
                        from payment.models import Wallet
                        wallet, _ = Wallet.objects.select_for_update().get_or_create(
                            user_id=bet.user_id,
                            defaults={'balance': Decimal('0.00')}
                        )
                        wallet.settle_win(bet.stake, payout)
                    except Exception:
                        from acc.models import User
                        User.objects.filter(id=bet.user_id).update(balance=models.F('balance') + payout)
            else:
                # Player crashed (lost)
                bet.status = Bet.Status.CRASHED
                bet.save(update_fields=['status'])
                if bet.user:
                    try:
                        from payment.models import Wallet
                        wallet = Wallet.objects.filter(user_id=bet.user_id).first()
                        if wallet:
                            wallet.settle_loss(bet.stake)
                    except Exception:
                        pass

    @staticmethod
    def place_bet(user, stake: Decimal, auto_cashout: Decimal = None) -> Bet:
        """
        Places a bet for an authenticated user on the current active round.
        Deducts funds atomically.
        """
        config = GameConfig.load()
        if stake < config.min_bet:
            raise ValidationError(f"Minimum stake is {config.min_bet} KES.")
        if stake > config.max_bet:
            raise ValidationError(f"Maximum stake is {config.max_bet} KES.")

        with transaction.atomic():
            from acc.models import User
            from payment.models import Wallet

            user_locked = User.objects.select_for_update().get(id=user.id)
            wallet, _ = Wallet.objects.select_for_update().get_or_create(
                user=user_locked,
                defaults={'balance': Decimal('0.00')}
            )

            if wallet.available_balance < stake:
                raise ValidationError(f"Insufficient wallet balance ({wallet.available_balance:.2f} KES). Please deposit funds or adjust stake.")

            # Ensure round is currently in BETTING phase
            active_round = EngineService.get_or_advance_current_round()
            if not active_round.is_betting:
                raise ValidationError("Betting is closed for this flight. Please wait for the next takeoff.")

            # Support up to 2 concurrent bets per user per round (Dual Aviator Panels)
            if active_round.bets.filter(user=user_locked, status__in=[Bet.Status.PENDING, Bet.Status.PLAYING]).count() >= 2:
                raise ValidationError("You can place a maximum of 2 bets per flight.")

            # Lock funds directly on the wallet (lock_funds also automatically syncs user.balance)
            wallet.lock_funds(stake)

            # Create bet
            bet = Bet.objects.create(
                round=active_round,
                user=user_locked,
                is_bot=False,
                player_name=user_locked.display_name,
                stake=stake,
                auto_cashout=auto_cashout,
                status=Bet.Status.PENDING
            )

            # Update round total stake
            GameRound.objects.filter(id=active_round.id).update(
                total_staked=models.F('total_staked') + stake
            )

        return bet

    @staticmethod
    def cashout_bet(user, bet_id: int) -> Tuple[Decimal, Decimal]:
        """
        Executes instant cashout for a player while flight is active.
        Verifies timestamp server-side.
        Returns: (cashout_multiplier, payout_amount)
        """
        now = timezone.now()
        config = GameConfig.load()

        with transaction.atomic():
            active_round = EngineService.get_or_advance_current_round()
            if not active_round.is_flying:
                raise ValidationError("Flight is not currently in progress.")

            bet = Bet.objects.select_for_update().filter(
                id=bet_id,
                user=user,
                round=active_round,
                status=Bet.Status.PLAYING
            ).first()

            if not bet:
                raise ValidationError("No active bet found for this round.")

            # Calculate server current multiplier
            elapsed = (now - active_round.scheduled_start_time).total_seconds()
            if elapsed >= active_round.flight_duration_seconds:
                # Flight already crashed before request reached server
                bet.status = Bet.Status.CRASHED
                bet.save(update_fields=['status'])
                raise ValidationError(f"Flight flew away at {active_round.crash_multiplier}x before cashout.")

            current_multiplier = flight_duration_to_multiplier(elapsed, growth_k=config.growth_rate_k)
            # Safety check: multiplier cannot exceed crash target
            if current_multiplier >= active_round.crash_multiplier:
                current_multiplier = active_round.crash_multiplier

            payout = round(bet.stake * current_multiplier, 2)

            # Mark bet cashed out
            bet.status = Bet.Status.CASHED_OUT
            bet.cashout_multiplier = current_multiplier
            bet.payout = payout
            bet.cashed_out_at = now
            bet.save(update_fields=['status', 'cashout_multiplier', 'payout', 'cashed_out_at'])

            # Credit user wallet
            try:
                from payment.models import Wallet
                wallet, _ = Wallet.objects.select_for_update().get_or_create(
                    user_id=user.id,
                    defaults={'balance': Decimal('0.00')}
                )
                wallet.settle_win(bet.stake, payout)
            except Exception:
                from acc.models import User
                User.objects.filter(id=user.id).update(balance=models.F('balance') + payout)

            # Track round payout
            GameRound.objects.filter(id=active_round.id).update(
                total_payout=models.F('total_payout') + payout
            )

        return current_multiplier, payout
