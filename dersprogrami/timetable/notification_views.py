"""Bildirimler: zil menüsü ve anlık bildirimler için JSON, geçmiş sayfası, merkezden duyuru."""

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import notifications
from .models import Institution, Notification


def _item(n):
    return {"id": n.id, "title": n.title, "body": n.body[:300], "level": n.level, "read": n.read_at is not None,
            "time": f"{timezone.localtime(n.created_at):%d.%m %H:%M}",
            "url": reverse("timetable:notification_open", args=[n.id]) if n.url else ""}


def api_list(request):
    """Zil menüsü: okunmamış sayısı ve son bildirimler; ?sonra=<kimlik> ile o kimlikten yeniler (anlık bildirim)."""
    mine = Notification.objects.filter(user=request.user)
    after = request.GET.get("sonra", "")
    data = {"unread": mine.filter(read_at__isnull=True).count(), "latest": [_item(n) for n in mine[:8]],
            "last_id": mine.values_list("id", flat=True).first() or 0}
    if after.isdigit():
        data["new"] = [_item(n) for n in mine.filter(id__gt=int(after), read_at__isnull=True).order_by("id")[:5]]
    return JsonResponse(data)


@require_POST
def api_read(request):
    """Okundu işareti: {"id": kimlik} ya da {"all": true}."""
    import json

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        body = {}
    qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
    if not body.get("all"):
        qs = qs.filter(pk=body.get("id") or 0)
    qs.update(read_at=timezone.now())
    return JsonResponse({"ok": True, "unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})


def open_notification(request, pk):
    """Bildirime tıklayınca: okundu sayılır ve bağlantısına gidilir."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if n.read_at is None:
        Notification.objects.filter(pk=n.pk).update(read_at=timezone.now())
    return redirect(n.url or "timetable:notifications")


def notification_list(request):
    """Bildirim geçmişi; okunmamışlar süzülebilir, hepsi okundu yapılabilir."""
    if request.method == "POST" and request.POST.get("action") == "all_read":
        n = Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        messages.info(request, f"{n} bildirim okundu olarak işaretlendi.")
        return redirect("timetable:notifications")
    qs = Notification.objects.filter(user=request.user).select_related("sender")
    unread_only = request.GET.get("okunmamis") == "1"
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    page = Paginator(qs, 50).get_page(request.GET.get("sayfa"))
    return render(request, "timetable/notifications.html", {
        "nav": "notifications", "page": page, "unread_only": unread_only,
        "unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count(),
    })


def broadcast(request):
    """Merkez paneli → Duyuru gönder: tüm kullanıcılara ya da bir kurumun üyelerine bildirim."""
    institutions = list(Institution.objects.order_by("name"))
    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        if not title:
            messages.error(request, "Başlık yazın.")
        else:
            institution = next((i for i in institutions if str(i.pk) == request.POST.get("kurum")), None)
            level = request.POST.get("level") if request.POST.get("level") in dict(Notification.LEVEL_CHOICES) else Notification.INFO
            url = (request.POST.get("url") or "").strip()
            if url and not url.startswith("/"):
                url = ""  # yalnızca bu sistemin içindeki sayfalar
            n = notifications.broadcast(request.user, title, (request.POST.get("body") or "").strip()[:2000], url, level, institution)
            messages.success(request, f"Duyuru {n} kullanıcıya gönderildi.")
            return redirect("timetable:broadcast")
    sent = (Notification.objects.exclude(broadcast="").values("broadcast", "title", "level", "created_at")
            .order_by("-created_at"))
    recent, seen = [], set()
    for row in sent:
        if row["broadcast"] not in seen:
            seen.add(row["broadcast"])
            row["count"] = Notification.objects.filter(broadcast=row["broadcast"]).count()
            row["read"] = Notification.objects.filter(broadcast=row["broadcast"], read_at__isnull=False).count()
            recent.append(row)
        if len(recent) >= 15:
            break
    return render(request, "timetable/broadcast.html", {"nav": "central", "institutions": institutions,
                                                        "levels": Notification.LEVEL_CHOICES, "recent": recent})
