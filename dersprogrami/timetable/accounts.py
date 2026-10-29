"""Merkez paneli, okul kullanıcıları ve hesap ayarları (çok okullu yapı)."""

from django import forms
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .access import grantable, institution_permissions
from .counts import related_count
from .data_views import default_periods
from .models import Institution, Membership, School
from .views import _nav

M = Membership


class NewUserForm(forms.Form):
    username = forms.CharField(label="Kullanıcı adı", max_length=150)
    first_name = forms.CharField(label="Ad", max_length=150, required=False)
    last_name = forms.CharField(label="Soyad", max_length=150, required=False)
    password = forms.CharField(label="Parola", widget=forms.PasswordInput, required=False,
                               help_text="Var olan bir kullanıcıyı eklerken boş bırakın.")

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        # Tüm yetkiler kabul edilir; verenin sahip olmadığı yetkiler kayıtta süzülür (_create_or_attach).
        self.fields["permissions"] = forms.MultipleChoiceField(
            label="Yetkiler", choices=M.PERMISSIONS, required=False, widget=forms.CheckboxSelectMultiple
        )
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "input"


def _perm_choices(allowed):
    return [(key, label) for key, label in M.PERMISSIONS if key in allowed and key != M.VIEW]


def _create_or_attach(form, institution, granter, allowed, programs=()):
    """Formdaki kullanıcıyı oluşturur ya da var olanı okula ekler. Dönüş: (membership, hata)."""
    data = form.cleaned_data
    username = data["username"].strip()
    perms = [p for p in data["permissions"] if p in allowed]
    user = User.objects.filter(username=username).first()
    if user is None:
        if not data["password"]:
            return None, "Yeni kullanıcı için parola girin."
        try:
            validate_password(data["password"])
        except ValidationError as exc:
            return None, " ".join(exc.messages)
        user = User.objects.create_user(username, password=data["password"],
                                        first_name=data["first_name"], last_name=data["last_name"])
    elif M.objects.filter(user=user, institution=institution).exists():
        return None, f"{username} zaten bu kurumun kullanıcısı."
    elif user.is_superuser:
        return None, "Merkez yönetici kurum kullanıcısı olarak eklenemez."
    membership = M.objects.create(user=user, institution=institution, permissions=perms, granted_by=granter)
    if programs:
        membership.programs.set(programs)
    return membership, None


def _can_manage(request, institution, membership):
    """Başkasının yetkisini yalnızca, onun yetkileri kendi yetkilerinin alt kümesiyse değiştirebilir."""
    if request.user.is_superuser:
        return True
    if membership.user_id == request.user.id or membership.user.is_superuser:
        return False
    return membership.perms <= institution_permissions(request.user, institution)


def _selected_programs(request, institution):
    ids = [int(x) for x in request.POST.getlist("programs") if str(x).isdigit()]
    return list(institution.programs.filter(pk__in=ids))


def school_users(request, pk):
    """Eski adres: programın kurumunun kullanıcı sayfasına yönlendirir."""
    school = get_object_or_404(School, pk=pk)
    return redirect("timetable:institution_users", pk=school.institution_id)


def institution_users(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    allowed = grantable(request.user, institution)
    choices = _perm_choices(allowed)
    form = NewUserForm(request.POST or None, choices=choices)
    if request.method == "POST":
        action = request.POST.get("action", "add")
        if action == "add":
            if form.is_valid():
                membership, error = _create_or_attach(
                    form, institution, request.user, allowed, _selected_programs(request, institution)
                )
                if error:
                    messages.error(request, error)
                else:
                    messages.success(request, f"{membership.user.username} eklendi.")
                    return redirect("timetable:institution_users", pk=institution.pk)
        else:
            membership = get_object_or_404(M, pk=request.POST.get("membership"), institution=institution)
            if not _can_manage(request, institution, membership):
                messages.error(request, "Bu kullanıcının yetkilerini değiştiremezsiniz (kendiniz ya da sizden yetkili).")
            elif action == "update":
                membership.permissions = [p for p in request.POST.getlist("permissions") if p in allowed]
                membership.save(update_fields=["permissions"])
                membership.programs.set(_selected_programs(request, institution))
                messages.success(request, f"{membership.user.username} yetkileri güncellendi.")
            elif action == "remove":
                membership.delete()
                messages.info(request, f"{membership.user.username} kurumdan çıkarıldı.")
            elif action == "password":
                user = membership.user
                if user.memberships.exclude(institution=institution).exists() and not request.user.is_superuser:
                    messages.error(request, "Başka kurumlarda da kayıtlı kullanıcının parolasını yalnızca merkez değiştirebilir.")
                else:
                    try:
                        validate_password(request.POST.get("password", ""), user)
                    except ValidationError as exc:
                        messages.error(request, " ".join(exc.messages))
                    else:
                        user.set_password(request.POST["password"])
                        user.save(update_fields=["password"])
                        messages.success(request, f"{user.username} parolası değiştirildi.")
            return redirect("timetable:institution_users", pk=institution.pk)
    members = []
    for m in institution.memberships.select_related("user", "granted_by").prefetch_related("programs"):
        members.append({"m": m, "manageable": _can_manage(request, institution, m),
                        "program_ids": [p.pk for p in m.programs.all()]})
    return render(request, "timetable/users.html", {
        "institution": institution, "nav": "users", "form": form, "members": members, "choices": choices,
        "programs": list(institution.programs.order_by("name")),
    })


def central(request):
    """Merkez paneli: tüm kurumlar, kurum ekleme ve kurum yöneticisi atama."""
    schools = Institution.objects.annotate(
        n_users=related_count(Membership, "institution"), n_programs=related_count(School, "institution"),
    ).order_by("name")
    users = User.objects.annotate(n_schools=Count("memberships")).order_by("-is_superuser", "username")
    form = NewUserForm(choices=_perm_choices(set(M.ALL)), initial={"permissions": M.ALL})
    return render(request, "timetable/central.html", {"schools": schools, "users": users, "form": form, "nav": "central"})


@require_POST
def central_school_new(request):
    name = (request.POST.get("school_name") or "").strip()
    form = NewUserForm(request.POST, choices=_perm_choices(set(M.ALL)))
    if not name:
        messages.error(request, "Okul adı girin.")
        return redirect("timetable:central")
    with transaction.atomic():
        school = Institution.objects.create(name=name[:200])
        program_name = (request.POST.get("program_name") or "").strip()
        if program_name:
            default_periods(School.objects.create(institution=school, name=program_name[:200]))
        if form.is_valid() and form.cleaned_data["username"].strip():
            membership, error = _create_or_attach(form, school, request.user, set(M.ALL))
            if error:
                transaction.set_rollback(True)
                messages.error(request, error)
                return redirect("timetable:central")
            messages.success(request, f"{school} oluşturuldu; yönetici: {membership.user.username}.")
        else:
            messages.success(request, f"{school} oluşturuldu.")
    return redirect("timetable:central")


def account(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    for field in form.fields.values():
        field.widget.attrs["class"] = "input"
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Parolanız değiştirildi.")
        return redirect("timetable:account")
    memberships = request.user.memberships.select_related("institution").prefetch_related("programs")
    return render(request, "timetable/account.html", {"form": form, "memberships": memberships, "nav": "account"})


def _audit_page(request, qs, context):
    from django.core.paginator import Paginator

    q = (request.GET.get("q") or "").strip()
    user = (request.GET.get("kullanici") or "").strip()
    program = request.GET.get("program") or ""
    start, end = request.GET.get("bas") or "", request.GET.get("bit") or ""
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(detail__icontains=q) | Q(program_name__icontains=q))
    if user:
        qs = qs.filter(username__iexact=user)
    if program.isdigit():
        qs = qs.filter(school_id=program)
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    page = Paginator(qs, 100).get_page(request.GET.get("sayfa"))
    usernames = sorted(set(qs.values_list("username", flat=True)))
    query = request.GET.copy()
    query.pop("sayfa", None)
    return render(request, "timetable/audit.html", {
        **context, "page": page, "usernames": usernames, "filters": {"q": q, "kullanici": user, "program": program, "bas": start, "bit": end},
        "query": query.urlencode(),
    })


def institution_log(request, pk):
    from .models import AuditLog

    institution = get_object_or_404(Institution, pk=pk)
    qs = AuditLog.objects.filter(institution=institution)
    return _audit_page(request, qs, {"institution": institution, "nav": "audit", "programs": institution.programs.order_by("name")})


def central_log(request):
    from .models import AuditLog

    return _audit_page(request, AuditLog.objects.all(), {"nav": "central", "central": True})


def backups(request):
    """Merkez → Yedekler: şimdi yedek al, indir, sil."""
    from django.http import FileResponse, Http404

    from . import backup

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            path = backup.path_of(request.POST.get("name"))
            if path:
                path.unlink()
                messages.info(request, f"{path.name} silindi.")
        elif action == "upload":
            try:
                path = backup.save_upload(request.FILES["dosya"]) if "dosya" in request.FILES else None
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                if path:
                    messages.success(request, f"Yedek dosyası alındı: {path.name}. Geri yüklemek için listeden seçin.")
        elif action == "restore":
            path = backup.path_of(request.POST.get("name"))
            if path is None or request.POST.get("onay", "").strip().upper() != "GERİ YÜKLE":
                messages.error(request, "Geri yükleme için yedeği seçip onay kutusuna GERİ YÜKLE yazın.")
                return redirect("timetable:backups")
            try:
                safety = backup.restore(path)
            except Exception as exc:  # bozuk ya da uyumsuz yedek: veritabanı değişmez
                messages.error(request, f"Geri yüklenemedi, veriler değişmedi: {exc}")
                return redirect("timetable:backups")
            # Oturumlar da silindi: giriş sayfasına
            return redirect(reverse("timetable:login") + f"?geri_yuklendi={path.name}&guvenlik={safety.name}")
        else:
            path = backup.create()
            messages.success(request, f"Yedek alındı: {path.name}")
        return redirect("timetable:backups")
    name = request.GET.get("indir")
    if name:
        path = backup.path_of(name)
        if path is None:
            raise Http404
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)
    from django.conf import settings

    return render(request, "timetable/backups.html", {
        "items": backup.listing(), "nav": "central", "keep": settings.BACKUP_KEEP, "dir": str(backup.directory()),
    })


def system_update(request):
    """Merkez → Sistem güncelleme: yeni sürümü denetle, önce yedek alıp indir, sunucuyu yeniden başlat."""
    from django.http import JsonResponse

    from . import backup, updater
    from .models import ImproveJob, Timetable

    if request.GET.get("durum"):  # yeniden başlatma sırasında sayfanın yokladığı sürüm bilgisi
        now = updater.current()
        return JsonResponse({"head": now["hash"] if now else ""})
    supervised = updater.supervised()
    git_ok = updater.is_git()
    running = Timetable.objects.filter(status=Timetable.RUNNING).count() + ImproveJob.objects.filter(
        status__in=[ImproveJob.QUEUED, ImproveJob.RUNNING]).count()
    if request.method == "POST":
        action = request.POST.get("action")
        if not supervised:
            messages.error(request, "Bu kurulum sayfadan yeniden başlatılamıyor; aşağıdaki açıklamaya bakın.")
            return redirect("timetable:system_update")
        if running and request.POST.get("zorla") != "1":
            messages.error(request, f"Şu an {running} üretim / iyileştirme çalışıyor; yeniden başlatma onları keser. "
                                    "Bitmesini bekleyin ya da yine de devam etmek için kutuyu işaretleyin.")
            return redirect("timetable:system_update")
        before = (updater.current() or {}).get("hash", "")
        if action == "guncelle":
            try:
                saved = backup.create()
            except Exception as exc:  # yedek alınamazsa güncellemeye girişilmez
                messages.error(request, f"Önce yedek alınamadı, güncelleme yapılmadı: {exc}")
                return redirect("timetable:system_update")
            ok, message = updater.pull()
            if not ok:
                messages.error(request, f"{message} (Yedek alındı: {saved.name})")
                return redirect("timetable:system_update")
            if (updater.current() or {}).get("hash", "") == before:
                messages.info(request, f"Zaten en son sürüm kullanılıyor. (Yedek alındı: {saved.name})")
                return redirect("timetable:system_update")
        elif action != "yeniden_baslat":
            return redirect("timetable:system_update")
        updater.request_restart(before)
        return render(request, "timetable/system_restart.html", {"before": before})
    check = updater.check() if git_ok and request.GET.get("denetle") else None
    return render(request, "timetable/system_update.html", {
        "supervised": supervised, "git_ok": git_ok, "current": updater.current() if git_ok else None,
        "changes": updater.local_changes() if git_ok else [], "check": check, "running": running,
        "last": updater.last_result(),
    })
