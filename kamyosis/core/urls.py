from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("organizasyon/", views.organizasyon, name="organizasyon"),
    path("bolum-yetkileri/", views.bolum_yetkileri, name="bolum_yetkileri"),
    path("birim/<slug:slug>/", views.birim, name="birim"),
]
