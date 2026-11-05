from django.urls import path

from . import sinav_yayini, views

app_name = "dersprogrami_kopru"

urlpatterns = [
    path("sinavlar/", views.sinavlar, name="sinavlar"),
    path("ac/", views.cerceve, name="cerceve"),
    path("sinav-programi/", sinav_yayini.liste, name="sinav_programi"),
    path("sinav-programi/<int:pk>/", sinav_yayini.donem, name="sinav_programi_donem"),
    path("sinav-programi/<int:pk>/excel/", sinav_yayini.excel, name="sinav_programi_excel"),
    path("sinav-programi/<int:pk>/yayin/", sinav_yayini.yayin, name="sinav_yayini"),
]
