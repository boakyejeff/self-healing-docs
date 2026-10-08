"""Shopex sample package (intentional doc drift for the demo)."""

from .cart import add_item, checkout
from .pricing import apply_promo

__all__ = ["add_item", "checkout", "apply_promo"]
