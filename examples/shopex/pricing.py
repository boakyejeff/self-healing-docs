"""Pricing helpers."""


def apply_promo(rate):
    """Apply a promotional discount rate.

    Args:
        rate (float): Discount rate between 0 and 1.

    Returns:
        float: The clamped rate.
    """
    return max(0.0, min(1.0, rate))
