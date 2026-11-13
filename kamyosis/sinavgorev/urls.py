from django.urls import path

from . import views

app_name = "sinavgorev"

urlpatterns = [
    path("", views.puantaj, name="puantaj"),
    path("personel/<int:pk>/", views.personel, name="personel"),
    path("isle/<int:period_pk>/", views.isle, name="isle"),
    path("elle/", views.elle_ekle, name="elle_ekle"),
    path("elle/<int:pk>/sil/", views.elle_sil, name="elle_sil"),
    path("roller/", views.roller, name="roller"),
    path("amir-ata/", views.amir_ata, name="amir_ata"),
]
