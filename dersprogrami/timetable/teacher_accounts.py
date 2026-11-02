"""Öğretmen hesapları: öğretmen kartlarına toplu kullanıcı açar; öğretmen Programım, İsteklerim, izin bildirimi ve telefon
takvimini kendi hesabıyla kullanır (kurum yetkisi verilmez).

E-postası olan öğretmene parola belirleme bağlantısı gönderilir (Django'nun parola sıfırlama anahtarıyla, tek
kullanımlık). E-postası olmayana tek seferlik geçici parola üretilir ve yalnızca o an ekranda gösterilir; öğretmen
ilk girişte parolasını değiştirir. Aynı bağlantı "Parolamı unuttum" akışında da kullanılır.
"""

import ipaddress
import re
import secrets
import socket

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import notify
from .access import account_is_local
from .models import School
from .textsort import natural_key

TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


def _base_username(teacher):
    if teacher.email and "@" in teacher.email:
        base = teacher.email.split("@")[0]
    else:
        base = f"{teacher.first_name.split()[0] if teacher.first_name else ''}.{teacher.last_name}"
    base = re.sub(r"[^a-z0-9._-]", "", base.translate(TR).lower()).strip("._-")
    return base[:140] or "ogretmen"


def unique_username(teacher):
    base = _base_username(teacher)
    name, n = base, 1
    while User.objects.filter(username__iexact=name).exists():
        n += 1
        name = f"{base}{n}"
    return name


CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale adresleri


def link_base(request):
    """E-postadaki bağlantının kökü ("http://adres:port") ya da güvenilir adres yoksa None.

    Bağlantı isteğin Host başlığından kurulursa, "*" kabul eden sunucuda saldırgan kendi alan adına giden bir
    parola bağlantısı gönderttirebilir. Bu yüzden: ayarlı PUBLIC_URL; yoksa Django'nun zaten denetlediği adlar;
    "*" iken yalnızca yerel ağ / Tailscale IP'si, *.ts.net adı ya da bu bilgisayarın adı."""
    if settings.PUBLIC_URL:
        return settings.PUBLIC_URL
    host = request.get_host()
    base = f"{request.scheme}://{host}"
    if "*" not in settings.ALLOWED_HOSTS:
        return base
    name = host.rsplit(":", 1)[0].strip("[]").lower() if not host.endswith("]") else host.strip("[]").lower()
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        trusted = name.endswith(".ts.net") or name in ("localhost", socket.gethostname().lower())
    else:
        trusted = ip.is_private or ip.is_loopback or ip in CGNAT
    return base if trusted else None


def set_password_link(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("timetable:password_set", args=[uid, token])
    return (link_base(request) or request.build_absolute_uri("/").rstrip("/")) + path


def _invite_message(request, school, teacher, user):
    link = set_password_link(request, user)
    body = "\n".join([
        f"Sayın {teacher.full_name},", "",
        f"{school.institution or school} ders programı sistemine sizin için bir hesap açıldı.", "",
        f"Kullanıcı adınız: {user.username}",
        "Parolanızı belirlemek için bağlantıyı açın (bağlantı bir kez kullanılabilir):", link, "",
        "Hesabınızla haftalık programınızı görebilir, gelemeyeceğiniz saatleri ve izinlerinizi bildirebilir, "
        "programınızı telefon takviminize ekleyebilirsiniz.",
    ])
    return EmailMessage(f"Ders programı hesabınız – {school}", body, to=[teacher.email])


def create_accounts(request, school, teachers, mode):
    """Seçili öğretmenlere hesap açar. Dönüş: (açılan, gönderilen e-posta, geçici parolalar [(öğretmen, kullanıcı, parola)], hatalar)."""
    created, temporary, mails, errors = 0, [], [], []
    with transaction.atomic():
        for teacher in teachers:
            user = teacher.user
            if user is None:
                user = User.objects.create_user(unique_username(teacher), email=teacher.email or "",
                                                first_name=teacher.first_name[:150], last_name=teacher.last_name[:150])
                user.set_unusable_password()
                user.save()
                teacher.user = user
                teacher.save(update_fields=["user"])
                created += 1
            elif not request.user.is_superuser and not account_is_local(user, school.institution):
                # Başka kurumda da kullanılan hesabın parolası/e-postası buradan değiştirilemez.
                errors.append(f"{teacher.full_name}: bağlı hesap ({user.username}) başka bir kurumda da kullanılıyor; "
                              "parolasını yalnızca hesabın sahibi ya da merkez yönetici değiştirebilir.")
                continue
            elif teacher.email and user.email != teacher.email:
                user.email = teacher.email
                user.save(update_fields=["email"])
            if teacher.email and mode in ("davet", "otomatik"):
                mails.append(_invite_message(request, school, teacher, user))
            elif mode in ("parola", "otomatik"):
                password = "-".join(secrets.token_hex(2) for _ in range(3))
                user.set_password(password)
                user.save(update_fields=["password"])
                temporary.append((teacher, user, password))
    sent = 0
    if mails:
        if notify.enabled():
            sent, errors = notify._send(mails)
        else:
            errors.append("E-posta sunucusu ayarlı değil; davetler gönderilemedi. Geçici parola seçeneğini kullanın.")
    return created, sent, temporary, errors


def page(request, pk):
    school = get_object_or_404(School, pk=pk)
    from .views import _nav

    teachers = sorted(school.teachers.select_related("user"), key=lambda t: natural_key(t.full_name))
    if request.method == "POST":
        action = request.POST.get("action")
        chosen = [t for t in teachers if str(t.pk) in set(request.POST.getlist("teacher"))]
        if not chosen:
            messages.warning(request, "Önce öğretmen seçin.")
            return redirect("timetable:teacher_accounts", pk=school.pk)
        if action == "ayir":
            for t in chosen:
                if t.user_id:
                    user = t.user
                    t.user = None
                    t.save(update_fields=["user"])
                    # Yalnızca öğretmen için açılmış (yetkisiz, başka kartı olmayan) hesap silinir.
                    if not user.is_superuser and not user.memberships.exists() and not user.teacher_profiles.exists():
                        user.delete()
            messages.success(request, f"{len(chosen)} öğretmenin hesap bağlantısı kaldırıldı.")
            return redirect("timetable:teacher_accounts", pk=school.pk)
        mode = action if action in ("davet", "parola", "otomatik") else "otomatik"
        created, sent, temporary, errors = create_accounts(request, school, chosen, mode)
        for e in errors[:8]:
            messages.error(request, e)
        if created or sent:
            messages.success(request, f"{created} hesap açıldı, {sent} davet e-postası gönderildi.")
        if temporary:
            # Geçici parolalar saklanmaz: yalnızca bu yanıtta gösterilir.
            return render(request, "timetable/teacher_accounts_passwords.html", _nav(school, "ogretmen-hesaplari", rows=temporary))
        return redirect("timetable:teacher_accounts", pk=school.pk)
    rows = [{"t": t, "status": "none" if not t.user_id else ("active" if t.user.last_login else "waiting")} for t in teachers]
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("none", "waiting", "active")}
    return render(request, "timetable/teacher_accounts.html", _nav(
        school, "ogretmen-hesaplari", rows=rows, counts=counts, with_email=sum(1 for t in teachers if t.email),
        mail_ready=notify.enabled()))


# --- parola belirleme ve "Parolamı unuttum" (giriş gerektirmez) -------------------------------------------------

password_set = login_not_required(auth_views.PasswordResetConfirmView.as_view(
    template_name="timetable/password_set.html", success_url=reverse_lazy("timetable:password_set_done")))
password_set_done = login_not_required(auth_views.PasswordResetCompleteView.as_view(
    template_name="timetable/password_set.html", extra_context={"done": True}))


class _ForgotForm(PasswordResetForm):
    """Davet edilip henüz parola belirlememiş (parolasız) hesaplara da bağlantı gönderir."""

    def get_users(self, email):
        return User.objects.filter(email__iexact=email, is_active=True)


class _ForgotView(auth_views.PasswordResetView):
    def form_valid(self, form):
        base = link_base(self.request)
        if base is None:  # güvenilmeyen adresle gelen istek: bağlantı gönderilmez, yanıt aynıdır (bilgi sızmaz)
            return redirect(self.get_success_url())
        scheme, _, domain = base.partition("://")
        self.extra_email_context = {"protocol": scheme, "domain": domain}
        self.domain_override = domain
        return super().form_valid(form)


password_forgot = login_not_required(_ForgotView.as_view(
    form_class=_ForgotForm, template_name="timetable/password_forgot.html", email_template_name="timetable/email/password_reset.txt",
    subject_template_name="timetable/email/password_reset_subject.txt", success_url=reverse_lazy("timetable:password_forgot_done")))
password_forgot_done = login_not_required(auth_views.PasswordResetDoneView.as_view(template_name="timetable/password_forgot.html"))

