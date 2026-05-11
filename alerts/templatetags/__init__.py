from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get an item from a dict by key — usage: dict|get_item:key"""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter
def split(value, delimiter=','):
    """Split a string by delimiter — usage: 'a,b,c'|split:',' """
    return [x.strip() for x in str(value).split(delimiter)]
