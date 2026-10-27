from django.urls import path

from . import data_views, views

app_name = "timetable"

urlpatterns = [
    path("", views.school_list, name="school_list"),
    path("ornek-okul/", views.create_demo, name="create_demo"),
    path("ice-aktar/", views.import_asc, name="import_asc"),
    path("okul/<int:pk>/", views.school_detail, name="school_detail"),
    path("okul/<int:pk>/uret/", views.generate, name="generate"),
    path("okul/<int:pk>/vekalet/", views.substitutions, name="substitutions"),
    path("okul/yeni/", data_views.school_create, name="school_create"),
    path("okul/<int:pk>/veri/okul/", data_views.school_settings, name="school_settings"),
    path("okul/<int:pk>/veri/dersler/", data_views.lessons, name="lessons"),
    path("okul/<int:pk>/veri/dersler/yeni/", data_views.lesson_edit, name="lesson_new"),
    path("okul/<int:pk>/veri/dersler/<int:lesson_id>/", data_views.lesson_edit, name="lesson_edit"),
    path("okul/<int:pk>/veri/dersler/<int:lesson_id>/sil/", data_views.lesson_delete, name="lesson_delete"),
    path("okul/<int:pk>/veri/dersler/sinif/<int:class_id>/", data_views.class_lessons, name="class_lessons"),
    path("okul/<int:pk>/veri/<slug:slug>/", data_views.entity_list, name="data_list"),
    path("okul/<int:pk>/veri/<slug:slug>/yeni/", data_views.entity_edit, name="data_new"),
    path("okul/<int:pk>/veri/<slug:slug>/<int:obj_id>/", data_views.entity_edit, name="data_edit"),
    path("okul/<int:pk>/veri/<slug:slug>/<int:obj_id>/sil/", data_views.entity_delete, name="data_delete"),
    path("program/<int:pk>/", views.timetable_detail, name="timetable_detail"),
    path("program/<int:pk>/durdur/", views.stop, name="stop"),
    path("program/<int:pk>/yayinla/", views.publish, name="publish"),
    path("program/<int:pk>/yazdir/", views.print_view, name="print"),
    path("program/<int:pk>/excel/", views.export_excel, name="export_excel"),
    path("program/<int:pk>/asc.xml", views.export_asc, name="export_asc"),
    path("api/program/<int:pk>/izgara/", views.api_grid, name="api_grid"),
    path("api/program/<int:pk>/durum/", views.api_status, name="api_status"),
    path("api/program/<int:pk>/onar/", views.api_repair, name="api_repair"),
    path("api/kart/<int:pk>/secenekler/", views.api_card_options, name="api_card_options"),
    path("api/kart/<int:pk>/tasi/", views.api_card_move, name="api_card_move"),
    path("api/kart/<int:pk>/cikar/", views.api_card_unplace, name="api_card_unplace"),
    path("api/kart/<int:pk>/kilit/", views.api_card_lock, name="api_card_lock"),
]
