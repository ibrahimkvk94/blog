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
]
