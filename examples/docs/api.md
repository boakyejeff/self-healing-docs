# API reference

## shopex.cart.add_item

Add a line to the cart:

```python
from shopex.cart import add_item

line = add_item("apple", 1.5, quantity=3)
```

## shopex.cart.checkout

Check out with `shopex.cart.checkout(cart, coupon)`.
