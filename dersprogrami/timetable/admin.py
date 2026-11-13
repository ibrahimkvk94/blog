from django.contrib import admin

from . import models


class PeriodInline(admin.TabularInline):
    model = models.Period
    extra = 0


@admin.register(models.School)
class SchoolAdmin(admin.ModelAdmin):
    inlines = [PeriodInline]


@admin.register(models.Building, models.Subject)
class SimpleAdmin(admin.ModelAdmin):
    list_filter = ["school"]


@admin.register(models.Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ["name", "capacity", "building", "school"]
    list_filter = ["school"]


@admin.register(models.Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ["__str__", "first_name", "last_name", "max_periods_per_day", "max_gaps_per_week", "max_days_per_week"]
    list_filter = ["school"]


class DivisionInline(admin.TabularInline):
    model = models.Division
    extra = 0
    show_change_link = True


@admin.register(models.SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ["name", "grade", "home_classroom", "school"]
    list_filter = ["school", "grade"]
    inlines = [DivisionInline]


class GroupInline(admin.TabularInline):
    model = models.Group
    extra = 0


@admin.register(models.Division)
class DivisionAdmin(admin.ModelAdmin):
    inlines = [GroupInline]


@admin.register(models.Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["__str__", "subject", "periods_per_week", "card_length"]
    list_filter = ["school", "subject"]
    filter_horizontal = ["classes", "groups", "teachers", "classrooms"]


@admin.register(models.Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ["__str__", "day", "period", "state"]
    list_filter = ["school", "state"]


class CardInline(admin.TabularInline):
    model = models.Card
    extra = 0


@admin.register(models.Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = ["name", "school", "status", "objective", "created_at"]
    list_filter = ["school", "status"]
    inlines = [CardInline]


@admin.register(models.CardRelationship)
class CardRelationshipAdmin(admin.ModelAdmin):
    list_display = ["name", "condition", "param", "apply_to", "importance", "active"]
    list_filter = ["school", "condition", "importance", "active"]
    list_editable = ["active"]
    filter_horizontal = ["lessons", "subjects", "classes", "teachers"]
    fieldsets = [
        (None, {"fields": ["school", "name", "active"]}),
        ("Kural", {"fields": ["condition", "param", "apply_to", "importance"]}),
        (
            "Kartlar",
            {
                "fields": ["lessons", "subjects", "classes", "teachers"],
                "description": "Ders veya ders adı seçin; sınıf ve öğretmen seçimi kümeyi daraltır. "
                "Hiç ders/ders adı seçilmezse tüm dersler kapsanır.",
            },
        ),
    ]


class SubstitutionInline(admin.TabularInline):
    model = models.Substitution
    extra = 0


@admin.register(models.Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ["teacher", "date", "reason"]
    list_filter = ["school", "date"]
    inlines = [SubstitutionInline]
