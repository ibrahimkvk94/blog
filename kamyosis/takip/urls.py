from django.urls import path

from . import views

app_name = "takip"

urlpatterns = [
    path("", views.gunluk, name="gunluk"),
    path("derslerim/", views.derslerim, name="derslerim"),
    path("devir/yeni/", views.devir_yeni, name="devir_yeni"),
    path("devir/", views.devirler, name="devirler"),
    path("devir/<uuid:blok>/karar/", views.devir_karar, name="devir_karar"),
    path("rapor/", views.rapor, name="rapor"),
]
