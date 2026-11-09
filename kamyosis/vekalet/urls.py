from django.urls import path

from . import views

app_name = "vekalet"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("islemler/", views.islemler, name="islemler"),
    path("islemler/<int:pk>/", views.islemler, name="duzenle"),
    path("islemler/<int:pk>/sonlandir/", views.sonlandir, name="sonlandir"),
    path("islemler/<int:pk>/sil/", views.sil, name="sil"),
]
