from decimal import Decimal, ROUND_HALF_UP

def compute_unit_price(product: dict) -> Decimal:
    """Price the customer actually pays per unit."""
    price = Decimal(str(product["price"]))
    if not product.get("is_sale") or not product.get("discount_type") or product.get("discount_value") is None:
        return price
    value = Decimal(str(product["discount_value"]))
    if product["discount_type"] == "percentage":
        price = price * (Decimal("100") - value) / Decimal("100")
    else:
        price = price - value
    return max(price, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def sale_fields_for_display(product: dict) -> dict:
    """Discount fields for customer-facing responses; nulls them when the sale is off."""
    on = bool(product.get("is_sale"))
    return {
        "is_sale": on,
        "discount_type": product.get("discount_type") if on else None,
        "discount_value": float(product["discount_value"]) if on and product.get("discount_value") is not None else None,
    }