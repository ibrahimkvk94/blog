"""Kurumsal basılı çıktı: program, nöbet ve değişiklik çıktılarının ortak başlığı (logo, kurum adı, dönem),
imza alanları ve sayfa altı. Ayarlar School.print_settings içinde; logo küçük bir data: adresi olarak saklanır
(ayrı dosya sunucusu gerekmez).
"""

import base64

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .models import School

LOGO_MAX = 300 * 1024
LOGO_TYPES = {"image/png", "image/jpeg", "image/svg+xml", "image/webp", "image/gif"}
SIGNATURES = 3


def settings_of(school):
    data = {"logo": "", "title": "", "term": "", "signatures": [], "footer": "", "sign_pages": True, "show_date": True}
    data.update(school.print_settings or {})
    rows = [s for s in data["signatures"] if s.get("role") or s.get("name")]
    data["signatures"] = rows
    data["title_lines"] = [line for line in data["title"].splitlines() if line.strip()]
    return data


def settings_page(request, pk):
    school = get_object_or_404(School, pk=pk)
    data = settings_of(school)
    if request.method == "POST":
        new = {
            "logo": data["logo"],
            "title": (request.POST.get("title") or "").strip()[:400],
            "term": (request.POST.get("term") or "").strip()[:200],
            "footer": (request.POST.get("footer") or "").strip()[:300],
            "sign_pages": request.POST.get("sign_pages") == "1",
            "show_date": request.POST.get("show_date") == "1",
            "signatures": [
                {"role": (request.POST.get(f"role-{i}") or "").strip()[:80], "name": (request.POST.get(f"name-{i}") or "").strip()[:80]}
                for i in range(SIGNATURES)
            ],
        }
        upload = request.FILES.get("logo")
        if request.POST.get("logo_clear") == "1":
            new["logo"] = ""
        elif upload is not None:
            if upload.content_type not in LOGO_TYPES:
                messages.error(request, "Logo PNG, JPG, SVG, WEBP ya da GIF olmalı.")
            elif upload.size > LOGO_MAX:
                messages.error(request, "Logo en fazla 300 KB olabilir.")
            else:
                new["logo"] = f"data:{upload.content_type};base64," + base64.b64encode(upload.read()).decode()
        # Çözücü verisi değil: veri sürümü artmaz (access.PLACEMENT_ONLY).
        School.objects.filter(pk=school.pk).update(print_settings=new)
        messages.success(request, "Basılı çıktı ayarları kaydedildi.")
        return redirect("timetable:print_settings", pk=school.pk)
    from .views import _nav

    rows = data["signatures"] + [{"role": "", "name": ""}] * (SIGNATURES - len(data["signatures"]))
    sample = school.active_timetable or school.timetables.filter(cards__day__isnull=False).distinct().first()
    return render(request, "timetable/print_settings.html", _nav(school, "baski", data=data, rows=rows[:SIGNATURES], sample=sample))
