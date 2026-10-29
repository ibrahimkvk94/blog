"""Sol menü, bölüm sekmeleri ve hızlı git (Ctrl+K) tek tanımdan üretilir: NAV_GROUPS.

Her öğe: (anahtar, ad, simge, url üretici, eşleşen nav/data_nav değerleri, gereken yetki, menüde görünür mü).
Bir sayfa açıkken onun grubu menüde açık gelir; Veri sayfalarının üstündeki sekmeler yalnızca o grubun sayfalarıdır.
"""

import json

from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

register = template.Library()


def _tt(name):
    return lambda s, tt: reverse(f"timetable:{name}", args=[tt.pk]) if tt else None


def _school(name, *extra):
    return lambda s, tt: reverse(f"timetable:{name}", args=[s.pk, *extra])


def _data(slug):
    return lambda s, tt: reverse("timetable:data_list", args=[s.pk, slug])


# (anahtar, başlık, öğeler); öğe: (ad, simge, url, eşleşenler, yetki, menüde)
NAV_GROUPS = [
    ("program", "Program", [
        ("Genel bakış", "layout", _school("school_detail"), {"dashboard"}, None, True),
        ("Ana görünüm", "grid", _tt("timetable_detail"), {"timetable"}, None, True),
        ("Çözüm merkezi", "wand", _tt("solution_center"), {"solution"}, "program", True),
        ("Kalite karnesi", "gauge", _tt("quality"), {"quality"}, None, True),
        ("Derslik doluluğu", "door", _tt("room_usage"), {"rooms"}, None, True),
        ("Raporlar", "printer", _tt("reports"), {"reports"}, None, True),
    ]),
    ("gunluk", "Günlük işler", [
        ("Vekâlet", "swap", _school("substitutions"), {"subs"}, None, True),
        ("Nöbet çizelgesi", "clipboard", _school("duties"), {"duties"}, None, True),
        ("Öğretmen istekleri", "inbox", _school("teacher_requests"), {"istekler"}, "veri", True),
    ]),
    ("veri", "Veri girişi", [
        ("Ayarlar ve saatler", "settings", _school("school_settings"), {"okul"}, "veri", True),
        ("Sınıflar", "layers", _data("siniflar"), {"siniflar"}, "veri", True),
        ("Öğretmenler", "user", _data("ogretmenler"), {"ogretmenler"}, "veri", True),
        ("Ders adları", "book", _data("ders-adlari"), {"ders-adlari"}, "veri", True),
        ("Derslikler", "building", _data("derslikler"), {"derslikler"}, "veri", True),
        ("Binalar", "building", _data("binalar"), {"binalar"}, "veri", False),
        ("Dersler", "list", _school("lessons"), {"dersler"}, "veri", True),
        ("Öğretmen atama", "user-plus", _school("teacher_assign"), {"ogretmen-atama"}, "veri", True),
        ("Ders dağıtımı", "columns", _school("distribution"), {"dagitim"}, "veri", True),
    ]),
    ("kurallar", "Kurallar", [
        ("Kart ilişkileri", "link", _data("kart-iliskileri"), {"kart-iliskileri"}, "veri", True),
        ("Derslik atama", "map-pin", _school("room_wizard"), {"derslik-atama"}, "veri", True),
        ("Toplu müsaitlik", "calendar-x", _school("bulk_availability"), {"toplu-musaitlik"}, "veri", True),
    ]),
    ("aktarim", "Aktarım ve ÜYBS", [
        ("Excel aktarımı", "upload", _school("excel_import"), {"excel"}, "veri", True),
        ("ÜYBS referansları", "file-text", _school("lesson_refs"), {"refs"}, "veri", True),
        ("ÜYBS şablonu ve TC", "file-text", _school("uybs_settings"), {"uybs"}, "veri", True),
        ("Öğrenciler ve seçmeliler", "cap", _school("students"), {"students"}, "veri", True),
    ]),
    ("yonetim", "Yönetim", [
        ("Web yayını", "globe", _school("publish_settings"), {"publish"}, "yayin", True),
        ("Kullanıcılar", "users", lambda s, tt: reverse("timetable:institution_users", args=[s.institution_id]), {"users"}, "kullanici", True),
    ]),
]


def build(context):
    """Yetkiye göre süzülmüş gruplar: [{"key", "title", "items": [...], "active", "badge"}]."""
    school = context.get("school")
    if school is None or not getattr(school, "pk", None):
        return []
    can = context.get("can") or {}
    tt = school.active_timetable or context.get("latest_timetable")
    current = {context.get("data_nav"), context.get("nav")}
    badges = {"istekler": context.get("pending_requests") or 0}
    groups = []
    for key, title, items in NAV_GROUPS:
        rows = []
        for label, icon, url, match, perm, visible in items:
            if perm and not can.get(perm):
                continue
            href = url(school, tt)
            if href is None:
                continue
            badge = sum(badges.get(m, 0) for m in match)
            rows.append({"label": label, "icon": icon, "url": href, "active": bool(match & current), "visible": visible,
                         "badge": badge})
        if rows:
            groups.append({"key": key, "title": title, "items": rows, "active": any(r["active"] for r in rows),
                           "badge": sum(r["badge"] for r in rows)})
    return groups


@register.inclusion_tag("timetable/nav/sidebar.html", takes_context=True)
def sidebar_nav(context):
    return {"groups": build(context)}


@register.inclusion_tag("timetable/nav/section_tabs.html", takes_context=True)
def section_tabs(context):
    """Açık sayfanın grubundaki sayfalar (birden fazlaysa) sekme olarak."""
    group = next((g for g in build(context) if g["active"]), None)
    return {"group": group if group and len(group["items"]) > 1 else None}


@register.simple_tag(takes_context=True)
def nav_pages_json(context):
    """Hızlı git (Ctrl+K) için sayfa listesi."""
    pages = [{"label": i["label"], "group": g["title"], "url": i["url"], "icon": i["icon"]}
             for g in build(context) for i in g["items"]]
    return mark_safe(json.dumps(pages, ensure_ascii=False).replace("</", "<\\/"))


PALETTE_ICONS = ("layout", "grid", "wand", "gauge", "door", "printer", "swap", "clipboard", "inbox", "settings", "layers", "user",
                 "book", "building", "list", "user-plus", "columns", "link", "map-pin", "calendar-x", "upload", "file-text", "cap",
                 "globe", "users")


@register.simple_tag
def palette_icons_json():
    """Hızlı git listesindeki simgelerin SVG'leri (bir kez üretilir)."""
    from django.template.loader import render_to_string

    icons = {name: render_to_string("timetable/icon.html", {"name": name}).strip() for name in PALETTE_ICONS}
    return mark_safe(json.dumps(icons).replace("</", "<\\/"))
