import time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from . import guvenilir, guvenlik
from . import iki_adim as ia
from .models import IkiAdimliDogrulama

BEKLEYEN = "iki_adim_bekleyen"   # parolası doğrulanmış, kodu beklenen giriş
KURULUM = "iki_adim_kurulum"     # açılırken üretilen, henüz onaylanmamış gizli anahtar
SURE = 5 * 60                    # kod girmek için süre (sn)
DENEME = 5                       # yanlış kod hakkı


class ParolaDegistirView(auth_views.PasswordChangeView):
    template_name = "registration/parola_degistir.html"
    success_url = reverse_lazy("core:panel")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        if user.parola_degismeli:
            user.parola_degismeli = False
            user.save(update_fields=["parola_degismeli"])
        kaldirilan = guvenilir.kaldir(user)  # parola değişince güvenilir cihazlar yeniden kod girer
        messages.success(self.request, "Parolanız değiştirildi." + (
            f" Güvenilir cihazlarınızın ({kaldirilan}) güveni kaldırıldı; bir sonraki girişte kod sorulur."
            if kaldirilan else ""))
        return response


def _iki_adim(user):
    return IkiAdimliDogrulama.objects.filter(kullanici=user, etkin=True).first()


class GirisView(auth_views.LoginView):
    """Parola doğruysa: iki adımlı doğrulaması açık kullanıcı için oturum açılmadan kod sayfasına geçilir.
    Hatalı denemeler kullanıcı adını kilitler; internetten girişte (ayar açıksa) iki adımlı doğrulama zorunludur."""

    redirect_authenticated_user = True

    def _hata(self, form, metin):
        return self.render_to_response(self.get_context_data(form=form, ozel_hata=metin))

    def post(self, request, *args, **kwargs):
        dk = guvenlik.kilit_kalan_dk(request.POST.get("username"))
        if dk:
            return self._hata(self.get_form(), f"Çok sayıda hatalı deneme yapıldı; bu hesap {dk} dakika sonra yeniden "
                                               "denenebilir.")
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        guvenlik.hatali_deneme(self.request.POST.get("username"))
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        guvenlik.basarili_giris(self.request.POST.get("username"))
        if _iki_adim(user) is None and not guvenlik.gelistirme_kodu():
            if guvenlik.dis_erisimde_iki_adim_gerekli(self.request):
                return self._hata(form, "İnternet üzerinden giriş için iki adımlı doğrulama gerekir. Önce kurum ağından "
                                        "giriş yapıp sağ üstteki menüden “İki adımlı doğrulama”yı açın.")
            return super().form_valid(form)
        cihaz = guvenilir.bu_cihaz(self.request, user)
        if cihaz is not None:  # “Bu cihaza güven” denilmiş tarayıcı: kod sorulmaz
            yanit = super().form_valid(form)
            guvenilir.kullanildi(self.request, yanit, cihaz)
            return yanit
        self.request.session[BEKLEYEN] = {
            "uid": user.pk, "backend": user.backend, "zaman": time.time(), "deneme": 0, "next": self.get_success_url(),
        }
        return redirect("giris_kodu")


@login_not_required
@never_cache
@sensitive_post_parameters("kod")
def giris_kodu(request):
    bekleyen = request.session.get(BEKLEYEN)
    if not bekleyen or time.time() - bekleyen.get("zaman", 0) > SURE:
        request.session.pop(BEKLEYEN, None)
        if bekleyen:
            messages.error(request, "Kod girme süresi doldu; yeniden giriş yapın.")
        return redirect("login")
    user = get_user_model().objects.filter(pk=bekleyen["uid"], is_active=True).first()
    kayit = _iki_adim(user) if user else None
    gelistirme = bool(guvenlik.gelistirme_kodu())
    if user is None or (kayit is None and not gelistirme):
        request.session.pop(BEKLEYEN, None)
        return redirect("login")
    hata = None
    if request.method == "POST":
        kod = request.POST.get("kod", "")
        adim, yedek = None, False
        ortak = gelistirme and guvenlik.gelistirme_kodu_dogru(kod)
        if not ortak and kayit is not None:
            adim = ia.dogrula(kayit.gizli, kod, kayit.son_adim)
            if adim is None:
                kalan, yedek = ia.yedek_kod_kullan(kayit.yedek_kodlar, kod)
        if ortak or adim is not None or yedek:
            if kayit is not None and not ortak:
                if adim is not None:
                    kayit.son_adim = adim
                else:
                    kayit.yedek_kodlar = kalan
                kayit.son_kullanim = timezone.now()
                kayit.save(update_fields=["son_adim", "yedek_kodlar", "son_kullanim"])
            hedef = bekleyen.get("next") or "/"
            request.session.pop(BEKLEYEN, None)
            auth_login(request, user, backend=bekleyen["backend"])
            if yedek:
                messages.warning(request, f"Yedek kodla giriş yaptınız; {kayit.kalan_yedek} yedek kodunuz kaldı. "
                                          "Telefonunuzu kaybettiyseniz iki adımlı doğrulamayı yeniden kurun.")
            if not url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
                hedef = "/"
            yanit = redirect(hedef)
            if request.POST.get("guven") == "1":
                guvenilir.guven(request, yanit, user)
                messages.info(request, "Bu cihaza güvenildi: güveni kaldırana dek burada kod sorulmayacak "
                                       "(sağ üst menü → İki adımlı doğrulama → Güvenilir cihazlar).")
            return yanit
        guvenlik.hatali_deneme(user.username)
        bekleyen["deneme"] = bekleyen.get("deneme", 0) + 1
        if bekleyen["deneme"] >= DENEME:
            request.session.pop(BEKLEYEN, None)
            messages.error(request, "Çok sayıda hatalı kod girildi; yeniden giriş yapın.")
            return redirect("login")
        request.session[BEKLEYEN] = bekleyen
        hata = f"Kod hatalı. {DENEME - bekleyen['deneme']} hakkınız kaldı."
    return render(request, "registration/giris_kodu.html", {"hata": hata, "kullanici": user, "kayit": kayit,
                                                            "gelistirme": gelistirme})


@login_required
@never_cache
@sensitive_post_parameters("kod", "parola")
def iki_adim_ayari(request):
    """Kişinin kendi iki adımlı doğrulama ayarı: aç (karekod + onay kodu), yedek kodları yenile, kapat."""
    user = request.user
    kayit = IkiAdimliDogrulama.objects.filter(kullanici=user).first()
    etkin = bool(kayit and kayit.etkin)
    yeni_yedekler = None
    if request.method == "POST":
        islem = request.POST.get("islem")
        if islem in ("cihaz_kaldir", "cihazlar_kaldir"):
            pk = request.POST.get("pk", "")
            hedef = None if islem == "cihazlar_kaldir" else (int(pk) if pk.isdigit() else -1)
            n = guvenilir.kaldir(user, hedef)
            yanit = redirect("iki_adim")
            if guvenilir.bu_cihaz(request, user) is None:
                yanit.delete_cookie(guvenilir.cerez_adi(user))
            messages.success(request, f"{n} cihazın güveni kaldırıldı; o cihazlarda bir sonraki girişte kod sorulur."
                             if n else "Kaldırılacak cihaz bulunamadı.")
            return yanit
        if islem == "baslat" and not etkin:
            request.session[KURULUM] = ia.gizli_uret()
        elif islem == "onayla" and not etkin:
            gizli = request.session.get(KURULUM)
            adim = ia.dogrula(gizli, request.POST.get("kod")) if gizli else None
            if adim is None:
                messages.error(request, "Kod doğrulanamadı. Uygulamadaki güncel kodu girin (telefonun saati doğru olmalı).")
            else:
                yedekler = ia.yedek_kodlar_uret()
                IkiAdimliDogrulama.objects.update_or_create(kullanici=user, defaults={
                    "gizli": gizli, "etkin": True, "son_adim": adim, "yedek_kodlar": [o for _k, o in yedekler],
                    "acilis": timezone.now(), "son_kullanim": timezone.now()})
                request.session.pop(KURULUM, None)
                yeni_yedekler = [k for k, _o in yedekler]
                messages.success(request, "İki adımlı doğrulama açıldı. Bundan sonra girişte uygulamadaki kod sorulacak.")
                kayit, etkin = _iki_adim(user), True
        elif islem in ("kapat", "yedek") and etkin:
            parola_dogru = user.check_password(request.POST.get("parola", ""))
            adim = ia.dogrula(kayit.gizli, request.POST.get("kod"), kayit.son_adim)
            if not parola_dogru or adim is None:
                messages.error(request, "Parola ya da uygulamadaki kod hatalı.")
            elif islem == "kapat":
                kayit.delete()
                messages.success(request, "İki adımlı doğrulama kapatıldı; girişte yalnızca parola sorulacak.")
                return redirect("iki_adim")
            else:
                yedekler = ia.yedek_kodlar_uret()
                kayit.yedek_kodlar = [o for _k, o in yedekler]
                kayit.son_adim = adim
                kayit.save(update_fields=["yedek_kodlar", "son_adim"])
                yeni_yedekler = [k for k, _o in yedekler]
                messages.success(request, "Yeni yedek kodlar oluşturuldu; eskileri artık geçmez.")
        elif islem == "vazgec":
            request.session.pop(KURULUM, None)
            return redirect("iki_adim")
        if yeni_yedekler is None:
            return redirect("iki_adim")
    gizli = None if etkin else request.session.get(KURULUM)
    adres = ia.otpauth_adresi(gizli, user.username) if gizli else None
    return render(request, "registration/iki_adim.html", {
        "kayit": kayit if etkin else None, "gizli": gizli, "gizli_gruplu": " ".join(gizli[i:i + 4] for i in range(0, len(gizli), 4)) if gizli else "",
        "karekod": ia.karekod_svg(adres) if adres else None, "yeni_yedekler": yeni_yedekler,
        "cihazlar": user.guvenilir_cihazlar.all(), "bu_cihaz": guvenilir.bu_cihaz(request, user),
    })


@login_not_required
def yonetim_girisi(request, extra_context=None):
    """Yönetim panelinin kendi giriş formu kullanılmaz: iki adımlı doğrulama atlanmasın diye KAMYOSİS girişine gider."""
    hedef = request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
        hedef = ""
    if request.user.is_authenticated:
        return redirect(hedef or "admin:index") if request.user.is_staff else redirect("core:panel")
    return redirect_to_login(hedef or reverse_lazy("admin:index"), "login")
