from django.urls import path

from . import views

app_name = "kimlik"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("oku/", views.oku, name="oku"),
    path("<int:pk>/", views.duzenle, name="duzenle"),
    path("toplu/", views.toplu, name="toplu"),
    path("aktar/", views.aktar, name="aktar"),
    path("excel/", views.excel_indir, name="excel"),
    path("excel/yukle/", views.excel_yukle, name="excel_yukle"),
    path("aktarilanlari-sil/", views.aktarilanlari_sil, name="aktarilanlari_sil"),
]
