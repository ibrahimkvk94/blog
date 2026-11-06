from django.urls import path

from . import views

app_name = "salon"

urlpatterns = [
    path("", views.yil, name="yil"),
    path("ay/<int:yil_no>/<int:ay_no>/", views.ay, name="ay"),
    path("gun/<str:tarih>/", views.gun, name="gun"),
    path("kayit/yeni/", views.yeni, name="yeni"),
    path("kayit/<int:pk>/", views.kayit, name="kayit"),
]
