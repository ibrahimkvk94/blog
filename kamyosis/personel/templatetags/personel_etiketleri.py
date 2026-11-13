from django import template

register = template.Library()


@register.filter
def maskele(deger, gorunur=4):
    """T.C. kimlik no gibi hassas numaraların son birkaç hanesi dışını gizler: 12345678901 → *******8901."""
    if not deger:
        return "–"
    deger = str(deger)
    return "•" * max(len(deger) - gorunur, 0) + deger[-gorunur:]
