import hmac
import hashlib
import math
import secrets
from decimal import Decimal
from typing import Tuple


def generate_round_secrets(client_seed: str = None) -> Tuple[str, str, str]:
    """
    Generates a secure 64-hex server seed, its public SHA-256 hash, and a client seed.
    """
    server_seed = secrets.token_hex(32)
    server_seed_hash = hashlib.sha256(server_seed.encode('utf-8')).hexdigest()
    if not client_seed:
        client_seed = secrets.token_hex(16)
    return server_seed, server_seed_hash, client_seed


def calculate_crash_multiplier(
    server_seed: str,
    client_seed: str,
    house_edge: Decimal = Decimal('0.0400'),
    instant_crash_rate: Decimal = Decimal('0.0400')
) -> Decimal:
    """
    Provably Fair crash point generator using HMAC-SHA256.
    
    Formula:
      1. HMAC-SHA256(server_seed, client_seed)
      2. Extract 52 bits -> float e in [0, 1)
      3. Instant crash test (house sweep at 1.00x)
      4. Inverse Pareto multiplier curve: (100 - H) / (100 * (1 - e))
    """
    hm = hmac.new(
        server_seed.encode('utf-8'),
        client_seed.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # Take first 52 bits (13 hex characters, 13 * 4 = 52)
    int_52 = int(hm[:13], 16)
    e = int_52 / (2 ** 52)

    # Instant crash check (e.g. 1 in 25 = 4%)
    rate_float = float(instant_crash_rate)
    if rate_float > 0:
        threshold = int(1.0 / rate_float)
        if int_52 % threshold == 0:
            return Decimal('1.00')

    # House edge calculation
    h = float(house_edge)
    raw_multiplier = (1.0 - h) / (1.0 - e)
    
    # Floor to 2 decimal places to favor the house slightly
    floored_multiplier = math.floor(raw_multiplier * 100.0) / 100.0
    final_val = max(1.00, floored_multiplier)

    # Cap astronomical multipliers to a safe maximum (e.g. 1000.00x)
    final_val = min(1000.00, final_val)

    return Decimal(f"{final_val:.2f}")


def multiplier_to_flight_duration(multiplier: Decimal, growth_k: float = 0.06) -> float:
    """
    Converts a multiplier to flight duration in seconds.
    Multiplier(t) = e^(k * t) => t = ln(Multiplier) / k
    """
    m_val = float(multiplier)
    if m_val <= 1.00:
        return 0.0
    duration = math.log(m_val) / growth_k
    return round(duration, 3)


def flight_duration_to_multiplier(seconds: float, growth_k: float = 0.06) -> Decimal:
    """
    Converts elapsed flight duration in seconds back to the active multiplier.
    """
    if seconds <= 0:
        return Decimal('1.00')
    m_val = math.exp(growth_k * seconds)
    return Decimal(f"{m_val:.2f}")
