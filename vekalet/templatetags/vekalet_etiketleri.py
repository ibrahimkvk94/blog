"""Teşkilat şeması, personel kartları ve birim kutularında yürürlükteki vekâlet notu: {% vekil_notu p %}."""

from django import template
from django.utils.html import format_html, format_html_join

from .. import servis

register = template.Library()


def _bitis(v):
    return "dönünceye kadar" if v.acik_uclu else f"bitiş {v.bitis:%d.%m}"


def _harita(context):
    request = context.get("request")
    if request is None:
        return servis.harita()
    if not hasattr(request, "_vekalet_haritasi"):
        request._vekalet_haritasi = servis.harita()
    return request._vekalet_haritasi


@register.simple_tag(takes_context=True)
def vekil_notu(context, p, kisa=False):
    """p vekâlet verdiyse "Vekili: X · 14.11'e kadar", vekilse "Vekâleten: <görev>". Yoksa boş."""
    if p is None or not getattr(p, "pk", None):
        return ""
    d = _harita(context).get(p.pk)
    if not d:
        return ""
    parcalar = []
    for v in d["asil"]:
        parcalar.append(("vk-not", "bi-arrow-left-right",
                         format_html("Vekili: <b>{}</b>{}", v.vekil.ad_soyad,
                                     "" if kisa else f" · {_bitis(v)}"),
                         f"{v.gorev}: {v.get_neden_display()}, {v.aralik_metni}"))
    for v in d["vekil"]:
        parcalar.append(("vk-not vk-not-vekil", "bi-person-up",
                         format_html("Vekâleten: <b>{}</b>{}", v.gorev, "" if kisa else f" · {_bitis(v)}"),
                         f"Asıl: {v.veren.ad_soyad} ({v.get_neden_display()}), {v.aralik_metni}"))
    return format_html_join("", '<span class="{}" title="{}"><i class="bi {}"></i>{}</span>',
                            ((s, t, i, m) for s, i, m, t in parcalar))
