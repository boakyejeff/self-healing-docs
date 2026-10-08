# Shopex usage guide

## shopex.apply_promotion

To discount an order, call `shopex.apply_promotion()` with a rate:

```python
from shopex import apply_promotion

total = shopex.apply_promotion(0.2)
```

See also the [API reference](api.md).
