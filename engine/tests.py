import hashlib
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import GameConfig, GameRound, Bet
from .generator import (
    generate_round_secrets,
    calculate_crash_multiplier,
    multiplier_to_flight_duration,
    flight_duration_to_multiplier
)
from .services import EngineService

User = get_user_model()


class EngineGeneratorTestCase(TestCase):
    def test_provably_fair_secret_generation(self):
        server_seed, server_seed_hash, client_seed = generate_round_secrets()
        self.assertEqual(len(server_seed), 64)
        self.assertEqual(len(server_seed_hash), 64)
        self.assertEqual(len(client_seed), 32)

        # Validate SHA-256 hash
        expected_hash = hashlib.sha256(server_seed.encode('utf-8')).hexdigest()
        self.assertEqual(server_seed_hash, expected_hash)

    def test_calculate_crash_multiplier_bounds(self):
        server_seed, _, client_seed = generate_round_secrets()
        multiplier = calculate_crash_multiplier(server_seed, client_seed)
        self.assertIsInstance(multiplier, Decimal)
        self.assertGreaterEqual(multiplier, Decimal('1.00'))
        self.assertLessEqual(multiplier, Decimal('1000.00'))

    def test_instant_crash_logic(self):
        # When instant crash rate is 1.0 (100%), it should always return 1.00
        mult = calculate_crash_multiplier("seed1", "client1", instant_crash_rate=Decimal('1.00'))
        self.assertEqual(mult, Decimal('1.00'))

    def test_duration_conversions(self):
        self.assertEqual(multiplier_to_flight_duration(Decimal('1.00')), 0.0)
        dur_2x = multiplier_to_flight_duration(Decimal('2.00'), growth_k=0.08)
        self.assertGreater(dur_2x, 5.0)
        
        # Test invertibility
        recovered_mult = flight_duration_to_multiplier(dur_2x, growth_k=0.08)
        self.assertEqual(recovered_mult, Decimal('2.00'))


class EngineStateMachineTestCase(TestCase):
    def setUp(self):
        self.config = GameConfig.load()
        self.config.betting_countdown_seconds = 2
        self.config.crashed_pause_seconds = 1
        self.config.save()

        self.user = User.objects.create_user(
            email='pilot@avingine.com',
            password='Password123!',
            first_name='John',
            last_name='Pilot'
        )

    def test_round_creation_and_bot_spawning(self):
        round_1 = EngineService.get_or_advance_current_round()
        self.assertEqual(round_1.status, GameRound.Status.BETTING)
        self.assertTrue(round_1.is_betting)
        self.assertFalse(round_1.is_flying)

        # Check bot bets were spawned
        bot_bets = round_1.bets.filter(is_bot=True)
        self.assertGreaterEqual(bot_bets.count(), self.config.min_bot_count)

    def test_user_bet_placement_and_balance_deduction(self):
        initial_balance = self.user.balance  # 1000.00
        stake = Decimal('100.00')

        bet = EngineService.place_bet(self.user, stake, auto_cashout=Decimal('2.50'))
        self.assertEqual(bet.stake, stake)
        self.assertEqual(bet.status, Bet.Status.PENDING)

        self.user.refresh_from_db()
        self.assertEqual(self.user.balance, initial_balance - stake)

    def test_insufficient_balance_rejected(self):
        self.user.balance = Decimal('20.00')
        self.user.save()

        with self.assertRaises(ValidationError):
            EngineService.place_bet(self.user, Decimal('100.00'))

    def test_cashout_flow(self):
        r = EngineService.get_or_advance_current_round()
        bet = EngineService.place_bet(self.user, Decimal('100.00'))

        # Fast forward time to FLYING
        r.scheduled_start_time = timezone.now() - timedelta(seconds=1)
        r.flight_duration_seconds = 10.0  # flight lasts 10s
        r.crash_multiplier = Decimal('5.00')
        r.status = GameRound.Status.FLYING
        r.save()

        bet.status = Bet.Status.PLAYING
        bet.save()

        # Cash out while flying
        mult, payout = EngineService.cashout_bet(self.user, bet.id)
        self.assertGreaterEqual(mult, Decimal('1.00'))
        self.assertGreater(payout, Decimal('100.00'))

        bet.refresh_from_db()
        self.assertEqual(bet.status, Bet.Status.CASHED_OUT)
        self.assertEqual(bet.cashout_multiplier, mult)


class EngineAPITestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='bettor@avingine.com',
            password='Password123!'
        )

    def test_api_game_state_unauthenticated(self):
        response = self.client.get('/play/api/state/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('server_timestamp', data)
        self.assertIn('round', data)
        self.assertIn('bets', data)
        self.assertFalse(data['user']['is_authenticated'])

    def test_api_game_state_authenticated(self):
        self.client.force_login(self.user)
        response = self.client.get('/play/api/state/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['user']['is_authenticated'])
        self.assertEqual(data['user']['balance'], 1000.0)

    def test_api_bet_placement(self):
        self.client.force_login(self.user)
        # Ensure round is in BETTING
        EngineService.get_or_advance_current_round()

        response = self.client.post(
            '/play/api/bet/place/',
            data='{"stake": 150.00, "auto_cashout": 2.00}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['new_balance'], 850.0)
