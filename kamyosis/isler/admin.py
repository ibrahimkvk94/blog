from django.contrib import admin

from .models import Is, IsNotu


class NotInline(admin.TabularInline):
    model = IsNotu
    extra = 0


@admin.register(Is)
class IsAdmin(admin.ModelAdmin):
    list_display = ["pk", "baslik", "durum", "oncelik", "onaylandi", "dis_erisim", "olusturma"]
    list_filter = ["durum", "oncelik"]
    inlines = [NotInline]
