from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from core.models import Yetki

from .models import GuvenlikAyari, GuvenilirCihaz, IkiAdimliDogrulama, User


class YetkiInline(admin.TabularInline):
    model = Yetki
    extra = 1
    autocomplete_fields = ["birim"]


@admin.register(User)
class KullaniciAdmin(UserAdmin):
    list_display = ["username", "first_name", "last_name", "bolum", "teskilat_birimi", "is_active", "is_superuser", "last_login"]
    list_filter = ["is_active", "is_superuser", "bolum"]
    search_fields = ["username", "first_name", "last_name"]
    autocomplete_fields = ["personel"]
    fieldsets = UserAdmin.fieldsets + (
        ("KAMYOSİS", {"fields": ["bolum", "teskilat_birimi", "personel", "parola_degismeli"]}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("KAMYOSİS", {"fields": ["bolum", "teskilat_birimi", "parola_degismeli"]}),
    )
    inlines = [YetkiInline]


@admin.register(IkiAdimliDogrulama)
class IkiAdimliDogrulamaAdmin(admin.ModelAdmin):
    """Telefonunu kaybeden kullanıcı için kayıt silinir: kullanıcı yalnızca parolayla girer ve yeniden kurar."""

    list_display = ["kullanici", "etkin", "kalan_yedek", "acilis", "son_kullanim"]
    list_filter = ["etkin"]
    search_fields = ["kullanici__username", "kullanici__first_name", "kullanici__last_name"]
    readonly_fields = ["kullanici", "etkin", "acilis", "son_kullanim"]
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    @admin.display(description="Kalan yedek kod")
    def kalan_yedek(self, obj):
        return obj.kalan_yedek


@admin.register(GuvenilirCihaz)
class GuvenilirCihazAdmin(admin.ModelAdmin):
    """Yönetici bir kullanıcının cihaz güvenini kaldırabilir (kaydı siler); ekleme yalnız girişte olur."""

    list_display = ["kullanici", "ad", "olusturma", "son_kullanim"]
    search_fields = ["kullanici__username", "kullanici__first_name", "kullanici__last_name"]
    readonly_fields = ["kullanici", "ad", "olusturma", "son_kullanim"]
    fields = readonly_fields

    def has_add_permission(self, request):
        return False


@admin.register(GuvenlikAyari)
class GuvenlikAyariAdmin(admin.ModelAdmin):
    list_display = ["__str__", "dis_erisimde_iki_adim_zorunlu", "giris_deneme_siniri", "kilit_suresi_dk", "kilit_katsayisi", "gelistirme_acik"]

    @admin.display(boolean=True, description="Geliştirme kodu")
    def gelistirme_acik(self, obj):
        return bool(obj.gelistirme_kodu)

    def has_add_permission(self, request):
        return not GuvenlikAyari.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
