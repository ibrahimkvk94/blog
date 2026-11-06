"""İlişkili kayıt sayıları alt sorguyla: birden çok Count(..., distinct=True) aynı sorguda tabloları birbiriyle
çarpar (sınıf × öğretmen × sürüm satırı) ve büyük programlarda sayfayı kilitler."""

from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce


def related_count(model, fk):
    """`model` tablosunda `fk` alanı dış sorgudaki kayda bağlı satırların sayısı."""
    rows = model.objects.filter(**{fk: OuterRef("pk")}).order_by().values(fk).annotate(n=Count("pk")).values("n")
    return Coalesce(Subquery(rows), 0)


def with_program_counts(schools):
    """Program listeleri için sınıf, öğretmen ve sürüm sayıları."""
    from .models import SchoolClass, Teacher, Timetable

    return schools.annotate(n_classes=related_count(SchoolClass, "school"), n_teachers=related_count(Teacher, "school"),
                            n_timetables=related_count(Timetable, "school"))
