from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter
def split(value, delimiter=','):
    return [x.strip() for x in str(value).split(delimiter)]

@register.filter
def idr(value):
    try:
        val = int(value)
        if val >= 1_000_000_000_000:
            return f'{val / 1_000_000_000_000:.1f}T'
        if val >= 1_000_000_000:
            return f'{val / 1_000_000_000:.1f}B'
        if val >= 1_000_000:
            return f'{val / 1_000_000:.1f}M'
        if val >= 1_000:
            return f'{val / 1_000:.1f}K'
        return str(val)
    except (TypeError, ValueError):
        return str(value)


@register.filter
def price(value, market='US'):
    """Format a numeric price with the right currency for the given market.

    Usage in template:
        {{ analysis.dcf.current_price|price:market }}

    US (and any non-ID market) -> "$ 421.92"
    ID                          -> "IDR 6,125"
    Falls back to the raw value if it can't parse.
    """
    if value in (None, '', '-'):
        return '-'
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    market = (market or 'US').upper()
    if market == 'ID':
        return f'IDR {num:,.0f}'
    return f'${num:,.2f}'
