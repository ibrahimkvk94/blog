from django.contrib import admin

from .models import NobetAtamasi, NobetAyari, NobetDonemi, NobetGorevi, NobetKisitlamasi, NobetKontenjani


@admin.register(NobetAyari)
class NobetAyariAdmin(admin.ModelAdmin):
    list_display = ["__str__", "yil_baslangic_ayi", "yatili_fark_siniri", "ardisik_ayni_gorev"]

    def has_add_permission(self, request):
        return not NobetAyari.objects.exists()


class KontenjanInline(admin.TabularInline):
    model = NobetKontenjani
    extra = 0
    verbose_name = "Bu ay farklı kişi sayısı"


@admin.register(NobetGorevi)
class NobetGoreviAdmin(admin.ModelAdmin):
    list_display = ["ad", "kisa_ad", "sira", "kontenjan", "yatili", "puan", "rutbeler", "sabit_sayisi", "aktif"]
    list_editable = ["sira", "kontenjan", "yatili", "puan", "aktif"]
    list_filter = ["yatili", "aktif", "renk", "sadece_sabit"]
    filter_horizontal = ["izinli_rutbeler"]
    autocomplete_fields = ["sabit_uyeler"]
    search_fields = ["ad", "kisa_ad"]
    inlines = [KontenjanInline]
    fieldsets = [
        (None, {"fields": ["ad", "kisa_ad", "sira", "renk", "aktif", "aciklama"]}),
        ("Dağıtım", {"fields": ["kontenjan", "izinli_rutbeler", "yatili", "puan"]}),
        ("Sabit görevliler", {"fields": ["sabit_uyeler", "sadece_sabit"],
                              "description": "Her ay önce bu kişiler yazılır (ör. yıl boyu Kütüphane veya Kadın Kursiyer)."}),
    ]

    @admin.display(description="Sabit")
    def sabit_sayisi(self, obj):
        return obj.sabit_uyeler.count() or "—"

    @admin.display(description="Tutabilecek rütbeler")
    def rutbeler(self, obj):
        return ", ".join(r.metin for r in obj.izinli_rutbeler.all()) or "—"


class AtamaInline(admin.TabularInline):
    model = NobetAtamasi
    extra = 0
    raw_id_fields = ["personel"]


@admin.register(NobetDonemi)
class NobetDonemiAdmin(admin.ModelAdmin):
    list_display = ["__str__", "durum", "olusturma", "kesin_zamani"]
    list_filter = ["durum", "yil"]
    inlines = [AtamaInline]


@admin.register(NobetKisitlamasi)
class NobetKisitlamasiAdmin(admin.ModelAdmin):
    list_display = ["personel", "tur", "baslangic", "bitis", "aciklama"]
    list_filter = ["tur"]
    search_fields = ["personel__ad_soyad", "aciklama"]
    autocomplete_fields = ["personel"]
    date_hierarchy = "baslangic"