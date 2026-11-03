"""Modül isteklerine KAMYOSİS kuralları: kapalı sayfalar, giriş yönlendirmesi, sınav yetkisi, yayında aktarım.

Ayarlarda MessageMiddleware'den sonra ve timetable.access.SchoolAccessMiddleware'den önce yer alır.
"""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render

from core.yetki import DUZENLEME, GORUNTULEME
from timetable.models import Membership as M

from .yetki import PROGRAM_BIRIMI, SINAV_BIRIMI, birim_yetkisi

log = logging.getLogger(__name__)

# KAMYOSİS'te kapalı sayfalar: süper kullanıcı dahil herkese 404 (rota adı → kullanıcıya gösterilen neden)
_SISTEM = "Sistem güncelleme, yedekleme ve merkez yönetimi KAMYOSİS tarafından yapılır."
_TEK_KURUM = "KAMYOSİS'te tek kurum vardır; yeni program kurum sayfasındaki “Program ekle” ile açılır."
_HESAP = "Kullanıcılar ve yetkiler KAMYOSİS yönetim panelinden verilir."
KAPALI = {
    # sistem güncelleme ve yedek (bütün veritabanını geri yükler / KAMYOSİS kodunu değiştirir)
    "system_update": _SISTEM, "backups": _SISTEM, "central": _SISTEM,
    "central_log": _SISTEM, "broadcast": _SISTEM,
    # yeni kurum ya da kurumsuz program açanlar
    "create_demo": _TEK_KURUM, "import_asc": _TEK_KURUM, "school_create": _TEK_KURUM, "central_school_new": _TEK_KURUM,
    # hesap ve yetki yönetimi
    "institution_users": _HESAP, "school_users": _HESAP, "teacher_accounts": _HESAP, "password_set": _HESAP,
    "password_set_done": _HESAP, "password_forgot": _HESAP, "password_forgot_done": _HESAP,
    # KAMYOSİS'in kendi nöbet ve devir (vekâlet) modülleri var
    "duties": "Nöbetler KAMYOSİS'in İdari İşler → Nöbet Grupları modülünden yürütülür.",
    "duties_print": "Nöbetler KAMYOSİS'in İdari İşler → Nöbet Grupları modülünden yürütülür.",
    "substitutions": "Ders devirleri (vekâlet) KAMYOSİS'in Ders Planları → ders takibi ekranından yapılır.",
    "public_board": "Ders devirleri (vekâlet) KAMYOSİS'in Ders Planları → ders takibi ekranından yapılır.",
}
# Yalnızca değişiklik isteği (POST) kapalı olanlar. backup_compare: "önceki başarılı üretimle karşılaştır" (GET)
# açık; yedeği ayrı kopyaya yükleyen karşılaştırma (POST) kapalı.
KAPALI_POST = {"backup_compare": _SISTEM}
# Modülün giriş ve hesap sayfası yerine KAMYOSİS'inkiler
YONLENDIR = {"account": "parola_degistir"}

SINAV_AD_ALANI = "sinav"  # Sınav Planlama modülünün adresleri (ders-programi/sinav-planlama/)
# Program Hazırlama yetkisi olmayıp yalnızca Sınav Planları'na girenlerin açabildiği Ders Planlama sayfaları;
# diğerleri (ortak veri sayfaları dahil) sınav ana sayfasına yönlendirilir.
SADECE_SINAV_ACIK = {"api_notifications", "api_notifications_read", "notifications", "api_presence", "exams_old",
                     "exam_period_old"}


def sadece_sinav(request):
    """Sınav Planları'nı görüp Program Hazırlama'yı görmeyen kullanıcı mı? Sonuç isteğe yazılır;
    modül menüsü de buna göre süzülür (bkz. apps.py)."""
    if not hasattr(request, "sadece_sinav"):
        u = request.user
        request.sadece_sinav = (u.is_authenticated and not u.is_superuser
                                and birim_yetkisi(u, PROGRAM_BIRIMI)[0] < GORUNTULEME
                                and birim_yetkisi(u, SINAV_BIRIMI)[0] >= GORUNTULEME)
    return request.sadece_sinav


class KopruMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        eslesme = request.resolver_match
        if (request.method == "POST" and response.status_code < 400 and eslesme is not None
                and eslesme.namespace == "timetable" and eslesme.url_name == "publish"):
            self._kamyosise_aktar(request, eslesme.kwargs.get("pk"))
        if (request.method == "POST" and response.status_code < 400 and eslesme is not None
                and eslesme.namespace == SINAV_AD_ALANI and eslesme.url_name == "proctors"
                and request.POST.get("action") == "exempt"):
            # Gözetmenler sayfasında değişen görev rolleri personele yazılır (roller KAMYOSİS'te tutulur)
            from sinav.models import ExamPeriod
            from sinavgorev.servis import rolleri_donemden_al

            period = ExamPeriod.objects.select_related("school").filter(pk=eslesme.kwargs.get("period_id")).first()
            if period is not None:
                rolleri_donemden_al(period)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        eslesme = request.resolver_match
        if eslesme is None:
            return None
        if eslesme.namespace == SINAV_AD_ALANI:
            if request.user.is_authenticated:
                sadece_sinav(request)  # menü süzmesi için
                self._sinav_yetkisi(request)
                if request.method == "POST" and (eslesme.url_name == "solve" or (
                        eslesme.url_name == "edit" and request.POST.get("action") == "auto_proctors")):
                    # gözetmen dağıtımından hemen önce sınav mazeretleri ve görev rolleri güncel olsun
                    from mazeret.servis import sinav_donemini_esitle

                    sinav_donemini_esitle(view_kwargs.get("period_id"))
            return None
        if eslesme.namespace != "timetable":
            return None
        ad = eslesme.url_name
        neden = KAPALI.get(ad) or (KAPALI_POST.get(ad) if request.method not in ("GET", "HEAD", "OPTIONS") else None)
        if neden:
            if not request.user.is_authenticated:  # ör. girişsiz vekâlet panosu
                raise Http404("Bu sayfa KAMYOSİS'te kullanılmıyor.")
            return render(request, "dersprogrami_kopru/kapali.html", {"neden": neden}, status=404)
        if ad == "login":
            return redirect_to_login(request.GET.get("next") or "/", settings.LOGIN_URL)
        if ad in YONLENDIR:
            return redirect(YONLENDIR[ad])
        if sadece_sinav(request) and ad not in SADECE_SINAV_ACIK:
            if request.method not in ("GET", "HEAD", "OPTIONS") or "/api/" in request.path:
                raise PermissionDenied("Ders Programı modülünde yalnızca sınav programına erişiminiz var.")
            return redirect("dersprogrami_kopru:sinavlar")
        return None

    def _sinav_yetkisi(self, request):
        """Sınav Planlama modülü "Sınav Planları" birimine bağlıdır: görmek için orada Görüntüleme, değişiklik için
        Düzenleme yetkisi gerekir (Program Hazırlama yetkisinden gelen veri girişi sınavda geçmez)."""
        seviye = birim_yetkisi(request.user, SINAV_BIRIMI)[0]
        okuma = request.method in ("GET", "HEAD", "OPTIONS")
        if not okuma and seviye < DUZENLEME:
            raise PermissionDenied("Sınav programında değişiklik için Sınav Planları biriminde Düzenleme yetkisi gerekir.")
        ek = set()
        if seviye >= GORUNTULEME:
            ek.add(M.VIEW)
        if seviye >= DUZENLEME:
            ek.add(M.DATA)
        request.timetable_extra_perms = ek

    def _kamyosise_aktar(self, request, timetable_pk):
        from timetable.models import Timetable

        from .yayin import AktarimHatasi, kamyosise_gonder

        timetable = Timetable.objects.select_related("school").filter(pk=timetable_pk).first()
        if timetable is None or timetable.school.active_timetable_id != timetable.pk:
            return  # yayınlanmadı (ör. üretilmemiş program)
        try:
            surum, rapor = kamyosise_gonder(timetable, request.user)
        except AktarimHatasi as e:
            messages.warning(request, f"KAMYOSİS'e aktarılmadı: {e}")
        except Exception:
            log.exception("Ders programı KAMYOSİS'e aktarılamadı (program %s)", timetable_pk)
            messages.warning(request, "Program yayınlandı ancak KAMYOSİS'e aktarılamadı. Sistem yöneticisine bildirin.")
        else:
            messages.info(request, f"KAMYOSİS'e taslak sürüm olarak aktarıldı: “{surum.ad}”. Ders Planları → "
                                   f"Program sürümleri ekranından öğretmen eşleştirmesi yapılıp başlangıç tarihiyle yayınlanır.")
            for uyari in rapor.uyarilar[:3]:
                messages.warning(request, uyari)
