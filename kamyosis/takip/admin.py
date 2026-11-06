from django.contrib import admin

from .models import AkademikDonem, DersKaydi, DevirTalebi, Gunluk, Tatil


@admin.register(AkademikDonem)
class AkademikDonemAdmin(admin.ModelAdmin):
    list_display = ["ad", "baslangic", "bitis"]


@admin.register(Tatil)
class TatilAdmin(admin.ModelAdmin):
    list_display = ["tarih", "aciklama"]
    date_hierarchy = "tarih"


@admin.register(DersKaydi)
class DersKaydiAdmin(admin.ModelAdmin):
    list_display = ["tarih", "hucre", "ogretmen"]
    list_filter = ["tarih"]
    date_hierarchy = "tarih"
    raw_id_fields = ["hucre", "ogretmen"]


@admin.register(DevirTalebi)
class DevirTalebiAdmin(admin.ModelAdmin):
    list_display = ["kayit", "yeni_personel", "durum", "isteyen", "istek_zamani"]
    list_filter = ["durum"]
    raw_id_fields = ["kayit", "yeni_personel"]


@admin.register(Gunluk)
class GunlukAdmin(admin.ModelAdmin):
    list_display = ["zaman", "kullanici", "islem"]
    list_filter = ["islem"]
    search_fields = ["ayrinti", "kullanici__username"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
