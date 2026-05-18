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
