"""Merkez paneli, okul kullanıcıları ve hesap ayarları (çok okullu yapı)."""

from django import forms
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .access import grantable, school_permissions
from .data_views import default_periods
from .models import Membership, School
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


def _create_or_attach(form, school, granter, allowed):
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
    elif M.objects.filter(user=user, school=school).exists():
        return None, f"{username} zaten bu okulun kullanıcısı."
    elif user.is_superuser:
        return None, "Merkez yönetici okul kullanıcısı olarak eklenemez."
    membership = M.objects.create(user=user, school=school, permissions=perms, granted_by=granter)
    return membership, None


def _can_manage(request, school, membership):
    """Başkasının yetkisini yalnızca, onun yetkileri kendi yetkilerinin alt kümesiyse değiştirebilir."""
    if request.user.is_superuser:
        return True
    if membership.user_id == request.user.id or membership.user.is_superuser:
        return False
    return membership.perms <= school_permissions(request.user, school)


def school_users(request, pk):
    school = get_object_or_404(School, pk=pk)
    allowed = grantable(request.user, school)
    choices = _perm_choices(allowed)
    form = NewUserForm(request.POST or None, choices=choices)
    if request.method == "POST":
        action = request.POST.get("action", "add")
        if action == "add":
            if form.is_valid():
                membership, error = _create_or_attach(form, school, request.user, allowed)
                if error:
                    messages.error(request, error)
                else:
                    messages.success(request, f"{membership.user.username} eklendi.")
                    return redirect("timetable:school_users", pk=school.pk)
        else:
            membership = get_object_or_404(M, pk=request.POST.get("membership"), school=school)
            if not _can_manage(request, school, membership):
                messages.error(request, "Bu kullanıcının yetkilerini değiştiremezsiniz (kendiniz ya da sizden yetkili).")
            elif action == "update":
                membership.permissions = [p for p in request.POST.getlist("permissions") if p in allowed]
                membership.save(update_fields=["permissions"])
                messages.success(request, f"{membership.user.username} yetkileri güncellendi.")
            elif action == "remove":
                membership.delete()
                messages.info(request, f"{membership.user.username} okuldan çıkarıldı.")
            elif action == "password":
                user = membership.user
                if user.memberships.exclude(school=school).exists() and not request.user.is_superuser:
                    messages.error(request, "Başka okullarda da kayıtlı kullanıcının parolasını yalnızca merkez değiştirebilir.")
                else:
                    try:
                        validate_password(request.POST.get("password", ""), user)
                    except ValidationError as exc:
                        messages.error(request, " ".join(exc.messages))
                    else:
                        user.set_password(request.POST["password"])
                        user.save(update_fields=["password"])
                        messages.success(request, f"{user.username} parolası değiştirildi.")
            return redirect("timetable:school_users", pk=school.pk)
    members = []
    for m in school.memberships.select_related("user", "granted_by"):
        members.append({"m": m, "manageable": _can_manage(request, school, m)})
    return render(request, "timetable/users.html", _nav(
        school, "users", form=form, members=members, choices=choices, all_perms=M.PERMISSIONS,
    ))


def central(request):
    """Merkez paneli: tüm okullar, okul ekleme ve okul yöneticisi atama."""
    schools = School.objects.annotate(
        n_users=Count("memberships", distinct=True), n_classes=Count("classes", distinct=True),
        n_teachers=Count("teachers", distinct=True), n_timetables=Count("timetables", distinct=True),
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
        school = School.objects.create(name=name[:200])
        default_periods(school)
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
    memberships = request.user.memberships.select_related("school")
    return render(request, "timetable/account.html", {"form": form, "memberships": memberships, "nav": "account"})
