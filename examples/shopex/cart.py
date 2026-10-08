"""Shopping cart helpers."""


def add_item(name, price, quantity=1):
    """Add an item to the cart.

    Args:
        name (str): Item name.
        price (float): Unit price.

    Returns:
        dict: The cart line.
    """
    return {"name": name, "price": price, "quantity": quantity}


def checkout(cart, coupon=None):
    """Check out the cart.

    Args:
        cart (list): The shopping cart lines.
        coupon_code (str): Discount coupon code.

    Returns:
        float: Total after discount.
    """
    total = sum(line["price"] * line["quantity"] for line in cart)
    return total
