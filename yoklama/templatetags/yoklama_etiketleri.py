from django import template

register = template.Library()


@register.filter
def bas_harfler(ad):
    """"Ali Can KAYA" → "AK" (ilk ve son sözcüğün baş harfi)."""
    parcalar = str(ad or "").split()
    if not parcalar:
        return "?"
    return (parcalar[0][:1] + (parcalar[-1][:1] if len(parcalar) > 1 else "")).upper()


@register.simple_tag
def isaretler(p):
    """Rütbe / sınıf / akademik unvan işaretleri: [(svg, etiket)]."""
    from yoklama.isaretler import personel_isaretleri

    return personel_isaretleri(p)


@register.filter
def girinti(derinlik):
    """Seçim kutusunda alt birim girintisi."""
    from django.utils.safestring import mark_safe

    return mark_safe("&nbsp;&nbsp;&nbsp;" * int(derinlik or 0) + ("└ " if derinlik else ""))
