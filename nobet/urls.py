from django.urls import path

from . import views

app_name = "nobet"

urlpatterns = [
    path("", views.ana, name="ana"),
    path("puantaj/", views.puantaj, name="puantaj"),
    path("yillik/", views.yillik, name="yillik"),
    path("yillik/olustur/", views.yillik_olustur, name="yillik_olustur"),
    path("yillik/hucre/", views.yillik_hucre, name="yillik_hucre"),
    path("personel/", views.personel, name="personel"),
    path("kisitlamalar/", views.kisitlamalar, name="kisitlamalar"),
    path("<int:yil>/<int:ay>/", views.donem, name="donem"),
    path("<int:yil>/<int:ay>/islem/", views.islem, name="islem"),
    path("<int:yil>/<int:ay>/excel/", views.excel, name="excel"),
]
