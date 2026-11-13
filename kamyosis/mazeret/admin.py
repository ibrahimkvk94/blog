from django.contrib import admin

from .models import (
    DersMazeretBildirimi, DersMazeretDonemi, DersMazeretGecmisi, SinavMazeretBildirimi, SinavMazeretDonemi,
    SinavMazeretGecmisi,
)


@admin.register(DersMazeretDonemi)
class DersMazeretDonemiAdmin(admin.ModelAdmin):
    list_display = ["ad", "giris_acik", "son_bildirim", "okul", "gun_sayisi", "saat_sayisi"]
    list_editable = ["giris_acik"]
    fields = ["ad", "giris_acik", "son_bildirim", "okul", "gun_sayisi", "saat_sayisi", "aciklama"]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        alan = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "okul" and alan is not None:  # programı buradan ekleme/silme kısayolları olmasın
            w = alan.widget
            w.can_add_related = w.can_change_related = w.can_delete_related = w.can_view_related = False
        return alan


class GecmisInline(admin.TabularInline):
    model = DersMazeretGecmisi
    extra = 0
    can_delete = False
    readonly_fields = ["zaman", "kullanici", "hucreler", "aciklama"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DersMazeretBildirimi)
class DersMazeretBildirimiAdmin(admin.ModelAdmin):
    list_display = ["personel", "donem", "yasak_sayisi", "kosullu_sayisi", "bildiren", "guncelleme"]
    list_filter = ["donem", "personel__bolum"]
    search_fields = ["personel__ad_soyad"]
    raw_id_fields = ["personel"]
    readonly_fields = ["bildiren", "guncelleme", "surum"]
    inlines = [GecmisInline]


@admin.register(SinavMazeretDonemi)
class SinavMazeretDonemiAdmin(admin.ModelAdmin):
    list_display = ["ad", "giris_acik", "son_bildirim", "sinav_donemi", "bildirimsize_gorev_yok"]
    list_editable = ["giris_acik"]
    fields = ["ad", "sinav_donemi", "giris_acik", "son_bildirim", "bildirimsize_gorev_yok", "aciklama"]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        alan = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "sinav_donemi" and alan is not None:  # sınav dönemi buradan eklenip silinmesin
            w = alan.widget
            w.can_add_related = w.can_change_related = w.can_delete_related = w.can_view_related = False
            alan.label_from_instance = lambda p: f"{p.school} · {p.name} ({p.start_date:%d.%m.%Y}–{p.end_date:%d.%m.%Y})"
        return alan


class SinavGecmisInline(GecmisInline):
    model = SinavMazeretGecmisi


@admin.register(SinavMazeretBildirimi)
class SinavMazeretBildirimiAdmin(DersMazeretBildirimiAdmin):
    inlines = [SinavGecmisInline]
