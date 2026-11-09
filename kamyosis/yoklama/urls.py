from django.urls import path

from . import musait_views, views

app_name = "yoklama"

urlpatterns = [
    path("", views.ana, name="ana"),
    path("onay/", views.onay, name="onay"),
    path("personel/<int:pk>/", views.kart, name="kart"),
    path("personel/<int:pk>/fotograf/", views.fotograf, name="fotograf"),
    path("personel/<int:pk>/fotograf/yukle/", views.fotograf_yukle, name="fotograf_yukle"),
    path("kayit/<int:pk>/", views.kayit, name="kayit"),
    path("izin-turleri/", views.turler, name="turler"),
    path("rapor/", views.rapor, name="rapor"),
    path("izin-dokumu/", views.izin_dokumu, name="izin_dokumu"),
    path("form/", views.yoklama_formu, name="form"),
    path("gruplar/", views.gruplar, name="gruplar"),
    path("gecmis/", views.gecmis, name="gecmis"),
    path("toplu-fotograf/", views.toplu_fotograf, name="toplu_fotograf"),
    path("musait/", musait_views.musait_personel, name="musait"),
]
