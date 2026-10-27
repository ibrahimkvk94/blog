from django.urls import path

from . import views

app_name = "timetable"

urlpatterns = [
    path("", views.school_list, name="school_list"),
    path("okul/<int:pk>/", views.school_detail, name="school_detail"),
    path("okul/<int:pk>/uret/", views.generate, name="generate"),
    path("program/<int:pk>/", views.timetable_detail, name="timetable_detail"),
    path("kart/<int:pk>/kilit/", views.toggle_lock, name="toggle_lock"),
]
