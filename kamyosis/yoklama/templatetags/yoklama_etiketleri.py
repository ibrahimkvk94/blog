from django import template

register = template.Library()


@register.filter
def bas_harfler(ad):
    """"Ali Can KAYA" → "AK" (ilk ve son sözcüğün baş harfi)."""
    parcalar = str(ad or "").split()
    if not parcalar:
        return "?"
    return (parcalar[0][:1] + (parcalar[-1][:1] if len(parcalar) > 1 else "")).upper()
