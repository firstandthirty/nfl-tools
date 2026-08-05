from __future__ import annotations


def american_to_decimal(american: int | float) -> float:
    odds = float(american)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds > 0:
        return 1.0 + odds / 100.0
    return 1.0 + 100.0 / abs(odds)


def decimal_to_american(decimal_odds: float) -> int:
    decimal_odds = float(decimal_odds)
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    if decimal_odds >= 2:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def american_implied_probability(american: int | float) -> float:
    odds = float(american)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def profit_per_unit_risked(american: int | float) -> float:
    odds = float(american)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds > 0:
        return odds / 100.0
    return 100.0 / abs(odds)


def break_even_probability(american: int | float) -> float:
    return american_implied_probability(american)


def expected_value_per_unit_risked(model_probability: float, american: int | float) -> float:
    probability = float(model_probability)
    if probability < 0 or probability > 1:
        raise ValueError("model_probability must be between 0 and 1")
    profit = profit_per_unit_risked(american)
    return probability * profit - (1 - probability)

