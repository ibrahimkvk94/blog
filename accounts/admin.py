from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from core.models import Yetki

from .models import User


class YetkiInline(admin.TabularInline):
    model = Yetki
    extra = 1
    autocomplete_fields = ["birim"]


@admin.register(User)
class KullaniciAdmin(UserAdmin):
    list_display = ["username", "first_name", "last_name", "bolum", "is_active", "is_superuser", "last_login"]
    list_filter = ["is_active", "is_superuser", "bolum"]
    search_fields = ["username", "first_name", "last_name"]
    autocomplete_fields = ["personel"]
    fieldsets = UserAdmin.fieldsets + (
        ("KAMYOSİS", {"fields": ["bolum", "personel", "parola_degismeli"]}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("KAMYOSİS", {"fields": ["bolum", "parola_degismeli"]}),
    )
    inlines = [YetkiInline]
