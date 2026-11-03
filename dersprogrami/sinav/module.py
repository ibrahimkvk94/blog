"""Sınav Planlama modülünün kaydı: ana sayfa kartı, sol menü, yetki tablosu ve işlem günlüğü adları
(bkz. timetable/modules.py)."""

from django.urls import reverse

from timetable.models import Membership
from timetable.modules import Module
from timetable.templatetags.navigation import data_url

M = Membership


def _sinav(name):
    return lambda s, tt: reverse(f"sinav:{name}", args=[s.pk])


def _lessons(s, tt):
    return reverse("timetable:lessons", args=[s.pk])


def _settings(s, tt):
    return reverse("timetable:school_settings", args=[s.pk])


NAV_GROUPS = [
    ("sinav", "Sınav planlama", [
        ("Sınav dönemleri", "calendar", _sinav("periods"), {"sinavlar"}, None, True),
        ("Ders sınav bilgileri", "list", _sinav("courses"), {"sinav-bilgileri"}, None, True),  # KAMYOSİS
    ]),
    # Ders Planlama ile ortak veri: sınavlar derslerden üretilir, salonlar derslik, gözetmenler öğretmendir.
    ("ortak", "Ortak veri", [
        ("Ayarlar ve saatler", "settings", _settings, {"okul"}, "veri", True),
        ("Sınıflar", "layers", data_url("siniflar"), {"siniflar"}, "veri", True),
        ("Öğretmenler", "user", data_url("ogretmenler"), {"ogretmenler"}, "veri", True),
        ("Ders adları", "book", data_url("ders-adlari"), {"ders-adlari"}, "veri", True),
        ("Derslikler", "building", data_url("derslikler"), {"derslikler"}, "veri", True),
        ("Dersler", "list", _lessons, {"dersler"}, "veri", True),
    ]),
]

MODULE = Module(
    key="sinav",
    title="Sınav Planlama",
    description="Vize, final ve bütünleme programı: derslerden sınav üretme, salon ve gözetmen ataması, çıktılar.",
    icon="calendar",
    namespace="sinav",
    landing="sinav:home",
    entry="sinav:periods",
    nav_groups=NAV_GROUPS,
    routes={
        "periods": (M.VIEW, M.DATA),
        "courses": (M.VIEW, M.DATA),  # KAMYOSİS: ders sınav bilgileri ve kontenjanlar
        "period": (M.VIEW, M.DATA),
        "solve": (M.VIEW, M.DATA),
        "results": (M.VIEW, M.DATA),
        "edit": (M.VIEW, M.DATA),
        "proctors": (M.VIEW, M.DATA),
        "print": (M.VIEW, M.VIEW),
        "excel": (M.VIEW, M.VIEW),
    },
    open_routes={"home"},
    labels={
        "periods": "Sınav dönemi ekledi", "period": "Sınav dönemini düzenledi", "solve": "Sınav programı oluşturdu",
        "results": "Sınav programı işlemi", "edit": "Sınavı düzenledi", "proctors": "Gözetmen ayarları",
        "print": "Sınav programı yazdırdı", "excel": "Sınav programı Excel",
        "courses": "Ders sınav bilgileri",
    },
    order=20,
)
