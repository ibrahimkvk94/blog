from django.contrib import admin

from .models import Satir, Takvim


class SatirInline(admin.TabularInline):
    model = Satir
    extra = 0


@admin.register(Takvim)
class TakvimAdmin(admin.ModelAdmin):
    list_display = ("ad", "yayinda", "yayin_zamani", "olusturma")
    inlines = [SatirInline]
