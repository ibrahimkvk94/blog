from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "KAMYOSİS Yönetim"
admin.site.site_title = "KAMYOSİS"
admin.site.index_title = "Sistem Yönetimi"

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("hesap/", include("accounts.urls")),
    path("personel/", include("personel.urls")),
    path("program/", include("program.urls")),
    path("takip/", include("takip.urls")),
    path("nobet/", include("nobet.urls")),
    path("mazeret/", include("mazeret.urls")),
    path("sinav-gorevleri/", include("sinavgorev.urls")),
    path("ders-programi/sinav-planlama/", include("sinav.urls")),  # timetable'dan önce
    path("ders-programi/", include("timetable.urls")),
    path("ders-programi-kopru/", include("dersprogrami_kopru.urls")),
    path("", include("core.urls")),
]
