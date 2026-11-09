from django.urls import path

from . import views

app_name = "mazeret"

urlpatterns = [
    path("ders/", views.liste, {"tur": "ders"}, name="ders"),
    path("ders/<int:donem_pk>/personel/<int:personel_pk>/", views.bildirim, {"tur": "ders"}, name="bildirim"),
    path("ders/<int:donem_pk>/toplu/", views.toplu, {"tur": "ders"}, name="toplu"),
    path("ders/<int:donem_pk>/aktar/", views.aktar, {"tur": "ders"}, name="aktar"),
    path("ders/<int:donem_pk>/tablo/", views.tablo, {"tur": "ders"}, name="tablo"),
    path("ders/<int:donem_pk>/teslim/", views.teslim, {"tur": "ders"}, name="teslim"),
    path("sinav/", views.liste, {"tur": "sinav"}, name="sinav"),
    path("sinav/<int:donem_pk>/personel/<int:personel_pk>/", views.bildirim, {"tur": "sinav"}, name="sinav_bildirim"),
    path("sinav/<int:donem_pk>/toplu/", views.toplu, {"tur": "sinav"}, name="sinav_toplu"),
    path("sinav/<int:donem_pk>/aktar/", views.aktar, {"tur": "sinav"}, name="sinav_aktar"),
    path("sinav/<int:donem_pk>/tablo/", views.tablo, {"tur": "sinav"}, name="sinav_tablo"),
    path("sinav/<int:donem_pk>/teslim/", views.teslim, {"tur": "sinav"}, name="sinav_teslim"),
]
