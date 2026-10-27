"""Çok okullu yapı: okul bazlı yetkilendirme.

- Merkez yönetici (süper kullanıcı) tüm okulları görür, okul ekler ve okul yöneticisi atar.
- Diğer kullanıcılar yalnızca üyesi oldukları okulları görür; her okulda ayrı yetki setleri vardır.
- "kullanici" yetkisi olan, o okulda yeni kullanıcı açıp yalnızca kendi sahip olduğu yetkileri
  verebilir (yetki devri).

Denetim tek yerde, SchoolAccessMiddleware'de yapılır: her istekte URL adından okul ve gereken yetki
çıkarılır. Yeni bir URL eklenince aşağıdaki tablolara da eklenmelidir; tabloda olmayan bir okul
URL'si varsayılan olarak yalnızca merkez yöneticiye açıktır (güvenli varsayılan).
"""

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render

from .models import Card, Membership, School, Timetable, TimetableVersion

M = Membership

# URL adı → (pk türü, GET için yetki, POST için yetki)
SCHOOL_ROUTES = {
    "school_detail": (M.VIEW, M.VIEW),
    "generate": (M.PROGRAM, M.PROGRAM),
    "substitutions": (M.VIEW, M.SUBSTITUTE),
    "duties": (M.VIEW, M.DUTY),
    "duties_print": (M.VIEW, M.VIEW),
    "school_settings": (M.VIEW, M.DATA),
    "lessons": (M.VIEW, M.DATA),
    "lesson_new": (M.VIEW, M.DATA),
    "lesson_edit": (M.VIEW, M.DATA),
    "lesson_delete": (M.DATA, M.DATA),
    "class_lessons": (M.VIEW, M.DATA),
    "distribution": (M.VIEW, M.DATA),
    "distribution_save": (M.DATA, M.DATA),
    "distribution_paste": (M.DATA, M.DATA),
    "copy_divisions": (M.DATA, M.DATA),
    "excel_import": (M.VIEW, M.DATA),
    "excel_export": (M.VIEW, M.VIEW),
    "data_list": (M.VIEW, M.DATA),
    "data_new": (M.VIEW, M.DATA),
    "data_edit": (M.VIEW, M.DATA),
    "data_delete": (M.DATA, M.DATA),
    "school_users": (M.USERS, M.USERS),
}
TIMETABLE_ROUTES = {
    "timetable_detail": (M.VIEW, M.VIEW),
    "stop": (M.PROGRAM, M.PROGRAM),
    "publish": (M.PUBLISH, M.PUBLISH),
    "print": (M.VIEW, M.VIEW),
    "export_excel": (M.VIEW, M.VIEW),
    "export_asc": (M.VIEW, M.VIEW),
    "api_grid": (M.VIEW, M.VIEW),
    "api_status": (M.VIEW, M.VIEW),
    "api_repair": (M.PROGRAM, M.PROGRAM),
    "api_undo": (M.PROGRAM, M.PROGRAM),
    "api_redo": (M.PROGRAM, M.PROGRAM),
    "api_bulk": (M.PROGRAM, M.PROGRAM),
    "api_versions": (M.VIEW, M.PROGRAM),
    "statistics": (M.VIEW, M.VIEW),
    "reports": (M.VIEW, M.VIEW),
    "report_render": (M.VIEW, M.VIEW),
    "api_row_action": (M.PROGRAM, M.PROGRAM),
    "api_cell_candidates": (M.VIEW, M.VIEW),
}
CARD_ROUTES = {
    "api_card_options": (M.VIEW, M.VIEW),
    "api_card_move": (M.PROGRAM, M.PROGRAM),
    "api_card_unplace": (M.PROGRAM, M.PROGRAM),
    "api_card_lock": (M.PROGRAM, M.PROGRAM),
    "api_card_info": (M.VIEW, M.VIEW),
    "api_card_room": (M.PROGRAM, M.PROGRAM),
    "api_lesson_quick": (M.DATA, M.DATA),
}
VERSION_ROUTES = {"api_version": (M.VIEW, M.PROGRAM)}
# Herkese açık (giriş yapmış) ve yalnızca merkez yöneticiye açık sayfalar
OPEN_ROUTES = {"school_list", "login", "logout", "account"}
CENTRAL_ROUTES = {"create_demo", "import_asc", "school_create", "central", "central_school_new"}


def school_permissions(user, school):
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(M.ALL)
    membership = M.objects.filter(user=user, school=school).first()
    return membership.perms if membership else set()


def visible_schools(user):
    if user.is_superuser:
        return School.objects.all()
    return School.objects.filter(memberships__user=user)


def _school_id(name, kwargs):
    pk = kwargs.get("pk")
    if name in SCHOOL_ROUTES:
        return pk
    if name in TIMETABLE_ROUTES:
        return Timetable.objects.filter(pk=pk).values_list("school_id", flat=True).first()
    if name in CARD_ROUTES:
        return Card.objects.filter(pk=pk).values_list("timetable__school_id", flat=True).first()
    if name in VERSION_ROUTES:
        return TimetableVersion.objects.filter(pk=pk).values_list("timetable__school_id", flat=True).first()
    return None


def _routes(name):
    for table in (SCHOOL_ROUTES, TIMETABLE_ROUTES, CARD_ROUTES, VERSION_ROUTES):
        if name in table:
            return table[name]
    return None


def _deny(request, message):
    if request.path.startswith("/api/") or request.headers.get("Content-Type", "").startswith("application/json"):
        return JsonResponse({"ok": False, "message": message}, status=403)
    return render(request, "timetable/forbidden.html", {"message": message}, status=403)


class SchoolAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None or match.namespace != "timetable" or not request.user.is_authenticated:
            return None
        name = match.url_name
        request.school_perms = set()
        if name in OPEN_ROUTES:
            return None
        if name in CENTRAL_ROUTES:
            return None if request.user.is_superuser else _deny(request, "Bu işlem yalnızca merkez yöneticiye açıktır.")
        routes = _routes(name)
        if routes is None:  # tabloda olmayan okul sayfası: güvenli varsayılan
            return None if request.user.is_superuser else _deny(request, "Bu sayfaya erişim yetkiniz yok.")
        school_id = _school_id(name, view_kwargs)
        if school_id is None:
            return None  # kayıt yok: görünüm 404 verir
        perms = school_permissions(request.user, School(pk=school_id))
        request.school_perms = perms
        needed = routes[1] if request.method not in ("GET", "HEAD", "OPTIONS") else routes[0]
        if not perms:
            return _deny(request, "Bu okula erişim yetkiniz yok.")
        if needed not in perms:
            label = dict(M.PERMISSIONS)[needed]
            return _deny(request, f"Bu işlem için “{label}” yetkiniz yok.")
        return None


def can(request):
    """Şablonlar için: {{ can.veri }} gibi."""
    perms = getattr(request, "school_perms", set())
    return {"can": {p: p in perms for p in M.ALL}}


def grantable(user, school):
    """Kullanıcının bu okulda başkasına verebileceği yetkiler."""
    perms = school_permissions(user, school)
    if M.USERS not in perms:
        return set()
    return perms


def ensure(condition, message="Bu işlem için yetkiniz yok."):
    if not condition:
        raise PermissionDenied(message)
