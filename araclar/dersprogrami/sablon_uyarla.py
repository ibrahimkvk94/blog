"""Ders Programı modülünün çerçeve şablonlarını KAMYOSİS'e uyarlar.

Modülün base.html ve nav/ribbon.html dosyalarından templates/timetable/ altında KAMYOSİS sürümleri üretir
(KAMYOSİS'in şablon klasörü modülünkinden önce arandığı için bunlar kullanılır). Modül güncellendiğinde
yeniden çalıştırılır; bir değişiklik bulunamazsa durur ve hangisi olduğunu söyler.

    .venv\\Scripts\\python.exe araclar\\dersprogrami\\sablon_uyarla.py
"""

import pathlib
import sys

KOK = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOK))
from config.dersprogrami_yolu import bul  # noqa: E402

KAYNAK = bul(KOK) / "timetable" / "templates" / "timetable"
HEDEF = KOK / "templates" / "timetable"

EV_SIMGESI = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></svg>')

DEGISIKLIKLER = {
    "base.html": [
        ("{% block title %}Ders Programı{% endblock %} · Ders Programı</title>",
         "{% block title %}Ders Programı{% endblock %} · KAMYOSİS</title>\n"
         "  <link rel=\"icon\" href=\"{% static 'img/favicon.ico' %}\" sizes=\"any\">"),
        ("      Ders Programı\n    </a>", "      KAMYOSİS · Ders Programı\n    </a>"),
        ("        {% if institution %}<a href=\"{% url 'timetable:institution_users' institution.pk %}\"", "        {% if False %}<a"),
        ("        {% if user.is_superuser %}<a href=\"{% url 'timetable:central' %}\"", "        {% if False %}<a"),
        ("        <a href=\"{% url 'timetable:account' %}\" class=\"{% if nav == 'account' %}active{% endif %}\">"
         "{% include \"timetable/icon.html\" with name=\"user\" %} <span class=\"nav-label\">Hesabım</span></a>",
         "        <a href=\"{% url 'core:panel' %}\">" + EV_SIMGESI + " <span class=\"nav-label\">KAMYOSİS ana sayfa</span></a>"),
        ("<a href=\"{% url 'timetable:account' %}\" style=\"color:inherit\">{% firstof user.get_full_name user.username %}</a>",
         "<a href=\"{% url 'core:panel' %}\" style=\"color:inherit;display:block;margin-bottom:6px\">← KAMYOSİS ana sayfa</a>"
         "<a href=\"{% url 'parola_degistir' %}\" style=\"color:inherit\">{% firstof user.get_full_name user.username %}</a>"),
        ("{% if user.is_superuser %} · <a href=\"{% url 'timetable:central' %}\" style=\"color:inherit\">Merkez</a>{% endif %}", ""),
        ("<a href=\"{% url 'timetable:logout' %}\" style=\"color:inherit\"", "<a href=\"{% url 'logout' %}\" style=\"color:inherit\""),
        ("<form id=\"logout-form\" method=\"post\" action=\"{% url 'timetable:logout' %}\" hidden>",
         "<form id=\"logout-form\" method=\"post\" action=\"{% url 'logout' %}\" hidden>"),
        # Yalnızca sınav yetkili kullanıcı (köprü request.sadece_sinav): Ders Planlama bağlantıları (ana sayfa,
        # Kurumlarım, kurum) ve arama yok
        ("        <a href=\"{% url 'timetable:home' %}\" class=\"{% if nav == 'home' %}active",
         "        {% if not request.sadece_sinav %}<a href=\"{% url 'timetable:home' %}\" class=\"{% if nav == 'home' %}active"),
        ("<span class=\"nav-label\">Kurumlarım</span></a>\n", "<span class=\"nav-label\">Kurumlarım</span></a>{% endif %}\n"),
        ("        <a href=\"{% url 'timetable:institution_detail' school.institution_id %}\">{{ school.institution }}</a>\n",
         "        {% if request.sadece_sinav %}<span>{{ school.institution }}</span>{% else %}"
         "<a href=\"{% url 'timetable:institution_detail' school.institution_id %}\">{{ school.institution }}</a>{% endif %}\n"),
        ("      <button type=\"button\" class=\"btn btn-ghost pal-open\" data-palette-open",
         "      {% if not request.sadece_sinav %}<button type=\"button\" class=\"btn btn-ghost pal-open\" data-palette-open"),
        ("<span>Ara</span><kbd>Ctrl K</kbd></button>", "<span>Ara</span><kbd>Ctrl K</kbd></button>{% endif %}"),
    ],
    "nav/ribbon.html": [
        # Yalnızca sınav yetkili kullanıcı: arama, ana sayfa ve Kurumlarım yok (Ders Planlama sayfalarına götürür).
        # Modül ve program seçicileri açık modülün (Sınav Planlama) sayfalarına gittiği için kalır.
        ("        <a href=\"{% url 'timetable:home' %}\" class=\"rb-btn",
         "        {% if not request.sadece_sinav %}<a href=\"{% url 'timetable:home' %}\" class=\"rb-btn"),
        ("<span>Kurumlarım</span></a>\n", "<span>Kurumlarım</span></a>{% endif %}\n"),
        ("      <button type=\"button\" class=\"rb-icon\" data-palette-open title=\"Hızlı git ve ara (Ctrl+K)\" aria-label=\"Ara\">"
         "{% include \"timetable/icon.html\" with name=\"search\" %}</button>\n",
         "      {% if not request.sadece_sinav %}<button type=\"button\" class=\"rb-icon\" data-palette-open "
         "title=\"Hızlı git ve ara (Ctrl+K)\" aria-label=\"Ara\">{% include \"timetable/icon.html\" with name=\"search\" %}"
         "</button>{% endif %}\n"),
        ("<span class=\"rb-brand-name\">Ders Programı</span>", "<span class=\"rb-brand-name\">KAMYOSİS · Ders Programı</span>"),
        ("    <div class=\"rb-tools\">\n",
         "    <div class=\"rb-tools\">\n      <a class=\"rb-icon\" href=\"{% url 'core:panel' %}\" title=\"KAMYOSİS ana sayfa\" "
         "aria-label=\"KAMYOSİS ana sayfa\">" + EV_SIMGESI + "</a>\n"),
        ("          <a href=\"{% url 'timetable:account' %}\">Hesabım</a>",
         "          <a href=\"{% url 'core:panel' %}\">KAMYOSİS ana sayfa</a>\n"
         "          <a href=\"{% url 'parola_degistir' %}\">Parola değiştir</a>"),
        ("          {% if user.is_superuser %}<a href=\"{% url 'timetable:central' %}\">Merkez paneli</a>{% endif %}\n", ""),
        ("        {% if institution %}<a href=\"{% url 'timetable:institution_users' institution.pk %}\"", "        {% if False %}<a"),
        ("        {% if user.is_superuser %}<a href=\"{% url 'timetable:central' %}\"", "        {% if False %}<a"),
        ("<a href=\"{% url 'timetable:account' %}\" class=\"rb-btn{% if nav == 'account' %} on{% endif %}\">"
         "{% include \"timetable/icon.html\" with name=\"user\" %}<span>Hesabım</span></a>",
         "<a href=\"{% url 'core:panel' %}\" class=\"rb-btn\">" + EV_SIMGESI + "<span>KAMYOSİS ana sayfa</span></a>"),
    ],
    "school_list.html": [
        ("  {% if user.is_superuser %}\n  <a class=\"btn\" href=\"{% url 'timetable:central' %}\">",
         "  {% if False %}\n  <a class=\"btn\">"),
        ("<form method=\"post\" action=\"{% url 'timetable:create_demo' %}\">", "<form method=\"post\">"),
        ("Henüz kurum yok. Merkez panelinden kurum ekleyin ya da örnek okul oluşturun.",
         "Henüz kurum yok. Sunucuda <code>manage.py migrate</code> çalıştırılınca kurum kendiliğinden açılır."),
        ("Henüz size atanmış bir kurum yok. Kurum yöneticinizden ya da merkezden yetki isteyin.",
         "Ders Programı yetkiniz yok. KAMYOSİS yöneticisinden “Program Hazırlama” yetkisi isteyin."),
    ],
    "institution.html": [
        ("\n  <a class=\"btn\" href=\"{% url 'timetable:institution_users' institution.pk %}\">"
         "{% include \"timetable/icon.html\" with name=\"users\" %} Kullanıcılar</a>{% endif %}", "{% endif %}"),
    ],
    "home.html": [  # modüllerin ana sayfası: merkez paneli KAMYOSİS'te kapalı
        ("{% if user.is_superuser %}<a class=\"btn\" href=\"{% url 'timetable:central' %}\">", "{% if False %}<a class=\"btn\">"),
    ],
}

UYARI = "{# KAMYOSİS: araclar/dersprogrami/sablon_uyarla.py ile modülün %s dosyasından üretildi; elle değiştirmeyin. #}\n"


def main():
    hata = False
    for ad, degisiklikler in DEGISIKLIKLER.items():
        metin = (KAYNAK / ad).read_text(encoding="utf-8").replace("\r\n", "\n")
        for eski, yeni in degisiklikler:
            if metin.count(eski) != 1:
                print(f"{ad}: bulunamadı ({metin.count(eski)} kez): {eski[:70]!r}")
                hata = True
                continue
            metin = metin.replace(eski, yeni)
        hedef = HEDEF / ad
        hedef.parent.mkdir(parents=True, exist_ok=True)
        if metin.startswith("{% load"):
            # base.html: {% load %} satırı doctype'tan önce aynı satırda; açıklama ondan sonra gelir
            ilk, _, kalan = metin.partition("<!doctype html>")
            metin = ilk + "<!doctype html>\n" + UYARI % ad + kalan.lstrip("\n")
        elif metin.startswith("{% extends"):
            ilk, _, kalan = metin.partition("\n")  # {% extends %} ilk etiket kalmalı
            metin = ilk + "\n" + UYARI % ad + kalan
        else:
            metin = UYARI % ad + metin
        hedef.write_text(metin, encoding="utf-8", newline="\n")
        print("yazıldı:", hedef.relative_to(KOK))
    return 1 if hata else 0


if __name__ == "__main__":
    sys.exit(main())
