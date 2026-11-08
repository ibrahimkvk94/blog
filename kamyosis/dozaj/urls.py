from django.urls import path

from . import views

app_name = "dozaj"

urlpatterns = [
    path("", views.tablo, name="tablo"),
    path("brans/<int:pk>/", views.brans, name="brans"),
    path("programlar/", views.programlar, name="programlar"),
    path("programlar/excel/", views.excel_yukle, name="excel"),
    path("program/<int:pk>/", views.program, name="program"),
    path("branslar/", views.branslar, name="branslar"),
    path("ogretim-elemanlari/", views.personel, name="personel"),
]
