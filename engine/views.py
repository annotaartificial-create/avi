import json
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import GameConfig, GameRound, Bet
from .services import EngineService


@require_GET
def api_game_state(request):
    """
    Lightweight state polling endpoint.
    Synchronizes the round state machine and returns:
    - Current round status & timestamp
    - Public seed hash (never secret multiplier while in-play)
    - Player's active bet & wallet balance
    - Live bets list (including realistic bots)
    - Recent multiplier history
    """
    now = timezone.now()
    active_round = EngineService.get_or_advance_current_round()
    config = GameConfig.load()

    # Base round payload
    round_data = {
        'id': active_round.id,
        'status': active_round.status,
        'server_seed_hash': active_round.server_seed_hash,
        'client_seed': active_round.client_seed,
        'scheduled_start_time': active_round.scheduled_start_time.timestamp(),
        'growth_rate_k': config.growth_rate_k,
        'crash_multiplier': float(active_round.crash_multiplier),
        'raw_multiplier': float(active_round.crash_multiplier),
    }

    if active_round.is_betting:
        time_left = max(0.0, (active_round.scheduled_start_time - now).total_seconds())
        round_data['betting_time_left'] = round(time_left, 2)
        round_data['betting_duration'] = config.betting_countdown_seconds

    elif active_round.is_flying:
        elapsed = max(0.0, (now - active_round.scheduled_start_time).total_seconds())
        round_data['elapsed_seconds'] = round(elapsed, 3)
        round_data['crash_multiplier'] = float(active_round.crash_multiplier)
        round_data['flight_duration'] = float(active_round.flight_duration_seconds)

    elif active_round.is_crashed:
        # Reveal secret crash point and server seed once crashed
        round_data['crash_multiplier'] = float(active_round.crash_multiplier)
        round_data['server_seed'] = active_round.server_seed
        round_data['crashed_at'] = active_round.crashed_at.timestamp() if active_round.crashed_at else now.timestamp()
        crashed_time = active_round.crashed_at or active_round.created_at
        pause_left = max(0.0, (crashed_time + timezone.timedelta(seconds=config.crashed_pause_seconds) - now).total_seconds())
        round_data['crashed_pause_left'] = round(pause_left, 2)

    # User-specific data (Support dual bet panels)
    user_bets_list = []
    user_balance = 0.0
    if request.user.is_authenticated:
        try:
            wallet = request.user.wallet
        except Exception:
            from payment.models import Wallet
            wallet, _ = Wallet.objects.get_or_create(
                user=request.user,
                defaults={'balance': Decimal('0.00')}
            )
        user_balance = float(wallet.available_balance)
        for ub in active_round.bets.filter(user=request.user):
            user_bets_list.append({
                'id': ub.id,
                'stake': float(ub.stake),
                'auto_cashout': float(ub.auto_cashout) if ub.auto_cashout else None,
                'status': ub.status,
                'cashout_multiplier': float(ub.cashout_multiplier) if ub.cashout_multiplier else None,
                'payout': float(ub.payout),
            })

    # Live Bets List for current round
    bets = active_round.bets.all().order_by('-stake')
    bets_payload = []
    for b in bets:
        bets_payload.append({
            'id': b.id,
            'player_name': b.player_name,
            'is_user': (request.user.is_authenticated and b.user_id == request.user.id),
            'is_bot': b.is_bot,
            'stake': float(b.stake),
            'auto_cashout': float(b.auto_cashout) if b.auto_cashout else None,
            'cashout_multiplier': float(b.cashout_multiplier) if b.cashout_multiplier else None,
            'payout': float(b.payout),
            'status': b.status,
        })

    # Recent crashed multipliers strip (last 15 rounds)
    recent_rounds = GameRound.objects.filter(
        status=GameRound.Status.CRASHED
    ).order_by('-id')[:15].values('id', 'crash_multiplier')
    
    recent_multipliers = [
        {'id': r['id'], 'multiplier': float(r['crash_multiplier'])}
        for r in recent_rounds
    ]

    return JsonResponse({
        'server_timestamp': now.timestamp(),
        'round': round_data,
        'user': {
            'is_authenticated': request.user.is_authenticated,
            'balance': user_balance,
            'active_bet': user_bets_list[0] if user_bets_list else None,
            'bets': user_bets_list,
        },
        'bets': bets_payload,
        'recent_multipliers': recent_multipliers,
        'limits': {
            'min_bet': float(config.min_bet),
            'max_bet': float(config.max_bet),
        }
    })


@require_POST
def api_place_bet(request):
    """
    Submits a player stake for the active/upcoming round.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Please sign in to place a bet.'}, status=401)

    try:
        body = json.loads(request.body)
        raw_stake = body.get('stake')
        raw_auto = body.get('auto_cashout')

        if not raw_stake:
            return JsonResponse({'success': False, 'error': 'Stake amount is required.'}, status=400)

        stake = Decimal(str(raw_stake)).quantize(Decimal('0.01'))
        auto_cashout = Decimal(str(raw_auto)).quantize(Decimal('0.01')) if raw_auto else None

        bet = EngineService.place_bet(request.user, stake, auto_cashout)

        # Refresh user wallet balance
        try:
            wallet = request.user.wallet
            wallet.refresh_from_db()
            new_balance = float(wallet.available_balance)
        except Exception:
            request.user.refresh_from_db()
            new_balance = float(request.user.balance)

        return JsonResponse({
            'success': True,
            'bet': {
                'id': bet.id,
                'stake': float(bet.stake),
                'auto_cashout': float(bet.auto_cashout) if bet.auto_cashout else None,
                'status': bet.status,
            },
            'new_balance': new_balance
        })

    except (ValueError, InvalidOperation):
        return JsonResponse({'success': False, 'error': 'Invalid stake format.'}, status=400)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e.message if hasattr(e, 'message') else e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Failed to place bet: {str(e)}'}, status=500)


@require_POST
def api_cashout(request):
    """
    Executes an instant cash out for the active player bet.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Please sign in.'}, status=401)

    try:
        body = json.loads(request.body)
        bet_id = body.get('bet_id')

        if not bet_id:
            return JsonResponse({'success': False, 'error': 'Bet ID is required.'}, status=400)

        multiplier, payout = EngineService.cashout_bet(request.user, bet_id)
        
        try:
            wallet = request.user.wallet
            wallet.refresh_from_db()
            new_balance = float(wallet.available_balance)
        except Exception:
            request.user.refresh_from_db()
            new_balance = float(request.user.balance)

        return JsonResponse({
            'success': True,
            'multiplier': float(multiplier),
            'payout': float(payout),
            'new_balance': new_balance
        })

    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e.message if hasattr(e, 'message') else e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Cashout error: {str(e)}'}, status=500)


def game_view(request):
    """
    Primary cockpit view for the crash game.
    """
    return render(request, 'engine/game.html')
