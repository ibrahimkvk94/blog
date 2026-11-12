from django.urls import path

from . import views

app_name = "sinavtakvimi"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yukle/", views.yukle, name="yukle"),
    path("<int:pk>/", views.takvim, name="takvim"),
    path("<int:pk>/excel/", views.excel, name="excel"),
    path("<int:pk>/duzenle/", views.duzenle, name="duzenle"),
    path("<int:pk>/yayin/", views.yayin, name="yayin"),
    path("<int:pk>/sil/", views.sil, name="sil"),
    path("malzemeler/", views.malzemeler, name="malzemeler"),
    path("<int:pk>/malzemeler/", views.malzemeler, name="malzemeler_takvim"),
    path("<int:pk>/malzemeler/kaydet/", views.malzeme_kaydet, name="malzeme_kaydet"),
    path("<int:pk>/malzemeler/excel/", views.malzeme_excel, name="malzeme_excel"),
    path("<int:pk>/malzemeler/sifirla/", views.malzeme_sifirla, name="malzeme_sifirla"),
    path("etut/", views.etutler, name="etutler"),
    path("<int:pk>/etut/", views.etutler, name="etutler_takvim"),
    path("<int:pk>/etut/kaydet/", views.etut_kaydet, name="etut_kaydet"),
    path("<int:pk>/etut/excel/", views.etut_excel, name="etut_excel"),
]
