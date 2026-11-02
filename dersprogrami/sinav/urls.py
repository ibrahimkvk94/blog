from django.urls import path

from . import views

app_name = "sinav"

urlpatterns = [
    path("", views.home, name="home"),
    path("program/<int:pk>/", views.period_list, name="periods"),
    path("program/<int:pk>/<int:period_id>/", views.period_page, name="period"),
    path("program/<int:pk>/<int:period_id>/olustur/", views.solve, name="solve"),
    path("program/<int:pk>/<int:period_id>/program/", views.results, name="results"),
    path("program/<int:pk>/<int:period_id>/sinav/<int:exam_id>/", views.exam_edit, name="edit"),
    path("program/<int:pk>/<int:period_id>/gozetmenler/", views.proctors, name="proctors"),
    path("program/<int:pk>/<int:period_id>/yazdir/", views.print_view, name="print"),
    path("program/<int:pk>/<int:period_id>/excel/", views.excel_view, name="excel"),
]
