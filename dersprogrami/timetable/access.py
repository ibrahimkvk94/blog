"""Çok kurumlu yapı: kurum bazlı yetkilendirme.

- Merkez yönetici (süper kullanıcı) tüm kurumları görür, kurum ekler ve kurum yöneticisi atar.
- Diğer kullanıcılar yalnızca üyesi oldukları kurumların programlarını görür (üyelik belirli
  programlarla sınırlanabilir); yetkiler kurum düzeyindedir.
- "kullanici" yetkisi olan, o kurumda yeni kullanıcı açıp yalnızca kendi sahip olduğu yetkileri
  verebilir (yetki devri). "programlar" yetkisi olan program ekler, aSc'den içe aktarır, siler.

Denetim tek yerde, SchoolAccessMiddleware'de yapılır: her istekte URL adından okul ve gereken yetki
çıkarılır. Yeni bir URL eklenince aşağıdaki tablolara da eklenmelidir; tabloda olmayan bir okul
URL'si varsayılan olarak yalnızca merkez yöneticiye açıktır (güvenli varsayılan).
"""

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render

import json

from .models import AuditLog, Card, Institution, Membership, School, Timetable, TimetableVersion

M = Membership

# URL adı → (pk türü, GET için yetki, POST için yetki)
SCHOOL_ROUTES = {
    "school_detail": (M.VIEW, M.VIEW),
    "quick_search": (M.VIEW, M.VIEW),
    "generate": (M.PROGRAM, M.PROGRAM),
    "substitutions": (M.VIEW, M.SUBSTITUTE),
    "duties": (M.VIEW, M.DUTY),
    "duties_print": (M.VIEW, M.VIEW),
    "lesson_refs": (M.VIEW, M.DATA),
    "uybs_settings": (M.VIEW, M.DATA),
    "print_settings": (M.DATA, M.DATA),
    "setup_wizard": (M.DATA, M.DATA),
    "teacher_accounts": (M.USERS, M.USERS),
    "departments": (M.DATA, M.DATA),
    "backup_compare": (M.DATA, M.DATA),
    "setup_wizard_start": (M.DATA, M.DATA),
    "relationship_import": (M.DATA, M.DATA),
    "bulk_availability": (M.DATA, M.DATA),
    "availability_import": (M.DATA, M.DATA),
    "room_wizard": (M.DATA, M.DATA),
    "teacher_requests": (M.DATA, M.DATA),
    "teacher_assign": (M.VIEW, M.DATA),
    "teacher_info": (M.DATA, M.DATA),
    "relation_wizard": (M.DATA, M.DATA),
    "relation_audit": (M.VIEW, M.DATA),
    "students": (M.VIEW, M.DATA),
    "student_timetable": (M.VIEW, M.VIEW),
    "publish_settings": (M.PUBLISH, M.PUBLISH),
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
    "program_delete": (M.PROGRAMS, M.PROGRAMS),
}
# pk = kurum
INSTITUTION_ROUTES = {
    "institution_detail": (M.VIEW, M.PROGRAMS),  # POST: kurum adı, program adı / taşıma, boş kurumu silme
    "institution_users": (M.USERS, M.USERS),
    "institution_log": (M.USERS, M.USERS),
    "program_new": (M.PROGRAMS, M.PROGRAMS),
    "program_copy": (M.PROGRAMS, M.PROGRAMS),
    "program_import": (M.PROGRAMS, M.PROGRAMS),
}
TIMETABLE_ROUTES = {
    "timetable_detail": (M.VIEW, M.VIEW),
    "stop": (M.PROGRAM, M.PROGRAM),
    "activate": (M.PROGRAM, M.PROGRAM),
    "publish": (M.PUBLISH, M.PUBLISH),
    "print": (M.VIEW, M.VIEW),
    "export_excel": (M.VIEW, M.VIEW),
    "export_asc": (M.VIEW, M.VIEW),
    "api_grid": (M.VIEW, M.VIEW),
    "api_status": (M.VIEW, M.VIEW),
    "api_repair": (M.PROGRAM, M.PROGRAM),
    "api_resolve": (M.PROGRAM, M.PROGRAM),
    "api_undo": (M.PROGRAM, M.PROGRAM),
    "api_redo": (M.PROGRAM, M.PROGRAM),
    "api_bulk": (M.PROGRAM, M.PROGRAM),
    "api_versions": (M.VIEW, M.PROGRAM),
    "statistics": (M.VIEW, M.VIEW),
    "reports": (M.VIEW, M.VIEW),
    "solution_center": (M.PROGRAM, M.PROGRAM),
    "penalty_breakdown": (M.VIEW, M.VIEW),
    "quality": (M.VIEW, M.PROGRAM),
    "pending": (M.VIEW, M.PROGRAM),
    "room_usage": (M.VIEW, M.VIEW),
    "school_improve": (M.PROGRAM, M.PROGRAM),
    "change_report": (M.VIEW, M.PROGRAM),
    "api_resolve_preview": (M.PROGRAM, M.PROGRAM),
    "report_render": (M.VIEW, M.VIEW),
    "report_excel": (M.VIEW, M.VIEW),
    "report_pdf": (M.VIEW, M.VIEW),
    "uybs_export": (M.VIEW, M.VIEW),
    "uybs_archive": (M.DATA, M.DATA),
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
OPEN_ROUTES = {"school_list", "login", "logout", "account", "password_set", "password_set_done", "password_forgot",
               "password_forgot_done", "department_portal", "my_requests", "my_timetable", "teacher_ics", "public_index", "public_board", "public_timetable",
               "notifications", "notification_open", "api_notifications", "api_notifications_read"}
CENTRAL_ROUTES = {"create_demo", "import_asc", "school_create", "central", "central_school_new", "central_log", "backups", "system_update", "broadcast"}


def _membership(user, institution_id):
    return M.objects.filter(user=user, institution_id=institution_id).prefetch_related("programs").first()


def school_permissions(user, school):
    """Kullanıcının bir programdaki yetkileri (kurum üyeliğinden; program kısıtı varsa ona göre)."""
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(M.ALL)
    institution_id = school.institution_id if school.institution_id else (
        School.objects.filter(pk=school.pk).values_list("institution_id", flat=True).first()
    )
    membership = _membership(user, institution_id)
    if membership is None:
        return set()
    allowed = {p.pk for p in membership.programs.all()}
    if allowed and school.pk not in allowed:
        return set()
    return membership.perms


def institution_permissions(user, institution):
    """Kurum düzeyindeki yetkiler. Belirli programlarla sınırlı üyeler kurum işlerini (program ekleme,
    kullanıcı yönetimi) yapamaz, yalnızca görüntüler."""
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(M.ALL)
    membership = _membership(user, institution.pk)
    if membership is None:
        return set()
    if membership.programs.exists():
        return {M.VIEW}
    return membership.perms


def visible_schools(user):
    if user.is_superuser:
        return School.objects.all()
    ids = set()
    for m in M.objects.filter(user=user).prefetch_related("programs", "institution__programs"):
        restricted = list(m.programs.all())
        ids.update(p.pk for p in (restricted or m.institution.programs.all()))
    return School.objects.filter(pk__in=ids)


def visible_institutions(user):
    if user.is_superuser:
        return Institution.objects.all()
    return Institution.objects.filter(memberships__user=user)


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
    for table in (SCHOOL_ROUTES, TIMETABLE_ROUTES, CARD_ROUTES, VERSION_ROUTES, INSTITUTION_ROUTES):
        if name in table:
            return table[name]
    return None


def _deny(request, message):
    if request.path.startswith("/api/") or request.headers.get("Content-Type", "").startswith("application/json"):
        return JsonResponse({"ok": False, "message": message}, status=403)
    return render(request, "timetable/forbidden.html", {"message": message}, status=403)


# Yalnızca kartların yerini değiştiren işlemler: çözücü problemi değişmez, önbellek korunur.
PLACEMENT_ONLY = set(CARD_ROUTES) | {
    "api_row_action", "api_undo", "api_redo", "api_bulk", "api_cell_candidates", "api_versions", "publish", "activate", "api_resolve",
    "report_excel", "report_pdf", "uybs_export", "uybs_archive", "substitutions", "duties", "solution_center", "quality", "pending", "school_improve", "change_report", "print_settings", "backup_compare",
}


def _bump_data_version(request):
    """Programın verisini değiştirmiş olabilecek her başarılı POST'ta veri sürümünü artır."""
    match = request.resolver_match
    school_id = getattr(request, "current_school_id", None)
    if match is None or school_id is None or match.url_name in PLACEMENT_ONLY:
        return
    from .problem_cache import bump

    bump(school_id)


class SchoolAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method == "POST" and response.status_code < 400:
            try:
                audit(request, response)
            except Exception:  # günlük yazılamasa da işlem bozulmasın
                pass
            _bump_data_version(request)
        return response

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
        if name in INSTITUTION_ROUTES:
            institution = Institution.objects.filter(pk=view_kwargs.get("pk")).first()
            if institution is None:
                return None
            request.current_institution_id = institution.pk
            perms = institution_permissions(request.user, institution)
        else:
            school_id = _school_id(name, view_kwargs)
            if school_id is None:
                return None  # kayıt yok: görünüm 404 verir
            perms = school_permissions(request.user, School(pk=school_id))
            request.current_school_id = school_id
            row = School.objects.filter(pk=school_id).values_list("institution_id", "name").first()
            if row:
                request.current_institution_id, request.current_program_name = row
        request.school_perms = perms
        needed = routes[1] if request.method not in ("GET", "HEAD", "OPTIONS") else routes[0]
        if not perms:
            return _deny(request, "Bu kuruma ya da programa erişim yetkiniz yok.")
        if needed not in perms:
            label = dict(M.PERMISSIONS)[needed]
            return _deny(request, f"Bu işlem için “{label}” yetkiniz yok.")
        return None


def can(request):
    """Şablonlar için: {{ can.veri }} ve kenar çubuğundaki program değiştirici."""
    perms = getattr(request, "school_perms", set())
    context = {"can": {p: p in perms for p in M.ALL}}
    school_id = getattr(request, "current_school_id", None)
    if school_id and request.user.is_authenticated:
        institution_id = School.objects.filter(pk=school_id).values_list("institution_id", flat=True).first()
        context["sibling_programs"] = visible_schools(request.user).filter(institution_id=institution_id).order_by("name")
        if M.DATA in perms:
            from .models import AvailabilityRequest

            from .models import LeaveRequest

            from .departments import pending_count

            context["pending_requests"] = (
                AvailabilityRequest.objects.filter(school_id=school_id, status=AvailabilityRequest.PENDING).count()
                + LeaveRequest.objects.filter(school_id=school_id, status=LeaveRequest.PENDING).count())
            context["pending_departments"] = pending_count(school_id)
    if request.user.is_authenticated:
        from .models import Teacher

        context["has_teacher_profile"] = Teacher.objects.filter(user=request.user).exists()
        context["my_departments"] = list(request.user.departments.all())
    return context


def grantable(user, institution):
    """Kullanıcının bu kurumda başkasına verebileceği yetkiler."""
    perms = institution_permissions(user, institution)
    if M.USERS not in perms:
        return set()
    return perms


def ensure(condition, message="Bu işlem için yetkiniz yok."):
    if not condition:
        raise PermissionDenied(message)


# --- işlem günlüğü -------------------------------------------------------------------------------

ACTION_LABELS = {
    "create_demo": "Örnek okul oluşturdu", "import_asc": "aSc'den kurum aktardı", "school_create": "Program oluşturdu",
    "central_school_new": "Kurum oluşturdu", "institution_users": "Kullanıcı yönetimi", "program_new": "Program ekledi",
    "program_copy": "Program kopyaladı", "program_import": "aSc'den program aktardı", "program_delete": "Program sildi",
    "generate": "Üretim başlattı", "stop": "Üretimi durdurdu", "publish": "Programı yayınladı", "activate": "Aktif programı değiştirdi",
    "substitutions": "Vekâlet", "duties": "Nöbet çizelgesi", "lesson_refs": "ÜYBS referansları",
    "penalty_breakdown": "Ceza dökümü",
    "uybs_settings": "ÜYBS ayarları", "print_settings": "Basılı çıktı ayarları", "setup_wizard": "Kurulum sihirbazı", "teacher_accounts": "Öğretmen hesapları", "departments": "Bölümler", "backup_compare": "Yedekle karşılaştırdı", "department_portal": "Bölüm önerisi", "relationship_import": "aSc kart ilişkisi aktarımı", "bulk_availability": "Toplu müsaitlik", "availability_import": "aSc müsaitlik aktarımı", "room_wizard": "Derslik atama", "school_improve": "Okul geneli iyileştirme", "change_report": "Değişiklik bildirimi gönderdi", "teacher_requests": "Öğretmen istekleri", "teacher_assign": "Öğretmen atama", "teacher_info": "Öğretmen bilgileri (toplu)", "relation_wizard": "Teori + uygulama sihirbazı", "relation_audit": "İlişki denetimi", "my_requests": "Müsaitlik isteği", "my_timetable": "Takvim bağlantısı", "solution_center": "Çözüm merkezi", "quality": "Kalite karnesi", "pending": "Bekleyen kart yerleştirme", "uybs_archive": "ÜYBS hafta arşivi", "students": "Öğrenciler",
    "school_settings": "Program ayarları/saatler", "lesson_new": "Ders ekledi", "lesson_edit": "Dersi düzenledi",
    "lesson_delete": "Ders sildi", "class_lessons": "Sınıf ders tablosu", "distribution_save": "Ders dağıtımı",
    "distribution_paste": "Ders dağıtımı (yapıştırma)", "copy_divisions": "Bölünme kopyaladı", "excel_import": "Excel'den veri aktardı",
    "data_list": "Kayıtları toplu düzenledi", "data_new": "Kayıt ekledi", "data_edit": "Kaydı düzenledi", "data_delete": "Kayıt sildi",
    "api_repair": "Bekleyenleri yerleştirdi", "api_resolve": "İhlalleri çözdü", "api_undo": "Geri aldı", "api_redo": "Yineledi", "api_bulk": "Toplu işlem",
    "api_versions": "Versiyon kaydetti", "api_version": "Versiyon işlemi", "api_row_action": "Satır işlemi",
    "api_card_move": "Kart taşıdı", "api_card_unplace": "Kartı kaldırdı", "api_card_lock": "Kart kilidi",
    "api_card_room": "Derslik değiştirdi", "api_lesson_quick": "Hızlı değişiklik", "reports": "Rapor şablonu",
    "account": "Parolasını değiştirdi", "backups": "Yedekleme", "system_update": "Sistem güncelleme", "broadcast": "Duyuru gönderdi", "institution_detail": "Kurumu düzenledi", "publish_settings": "Web yayını",
}
SKIP_AUDIT = {"login", "logout", "api_notifications_read", "notifications"}  # okundu işaretleri günlüğe yazılmaz


def _detail(request, response):
    parts = []
    if response.get("Content-Type", "").startswith("application/json"):
        try:
            message = json.loads(response.content or b"{}").get("message")
        except ValueError:
            message = None
        if message:
            parts.append(message)
    storage = getattr(request, "_messages", None)
    for m in getattr(storage, "_queued_messages", []) or []:
        parts.append(str(m))
    extra = request.POST.get("action") or (request.POST.get("name") if "name" in request.POST else "")
    if extra and not parts:
        parts.append(str(extra))
    return " · ".join(parts)[:2000]


def audit(request, response, action=None, detail=None):
    match = getattr(request, "resolver_match", None)
    if match is None or match.namespace != "timetable" or match.url_name in SKIP_AUDIT or not request.user.is_authenticated:
        return
    school_id = getattr(request, "current_school_id", None)
    if school_id and not School.objects.filter(pk=school_id).exists():
        school_id = None  # işlemde silinmiş (program silme)
    institution_id = getattr(request, "current_institution_id", None)
    if institution_id and not Institution.objects.filter(pk=institution_id).exists():
        institution_id = None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    AuditLog.objects.create(
        user=request.user, username=request.user.get_username(), institution_id=institution_id, school_id=school_id,
        program_name=getattr(request, "current_program_name", ""),
        action=action or ACTION_LABELS.get(match.url_name, match.url_name), detail=detail if detail is not None else _detail(request, response),
        path=request.path[:300], ip=forwarded or request.META.get("REMOTE_ADDR") or None,
    )


def _on_login(sender, request, user, **kwargs):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() if request else ""
    AuditLog.objects.create(user=user, username=user.get_username(), action="Giriş yaptı",
                            ip=forwarded or (request.META.get("REMOTE_ADDR") if request else None) or None)


def _on_login_failed(sender, credentials, request=None, **kwargs):
    AuditLog.objects.create(username=str(credentials.get("username", ""))[:150], action="Başarısız giriş denemesi",
                            ip=(request.META.get("REMOTE_ADDR") if request else None) or None)
