"""Teori + uygulama sihirbazının kurduğu ilişkilere kendi kısmının sınıf süzgecini ekler.

Seçilen ders artık kendi ders adını temsil ediyor (süzgeçsiz kural o dersin okutulduğu bütün kısımlara uygulanır);
sihirbazın kısım kısım kurduğu ilişkiler eskisi gibi yalnızca kendi kısmında kalsın diye.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    CardRelationship = apps.get_model("timetable", "CardRelationship")
    for rel in CardRelationship.objects.filter(name__startswith="Teori + uygulama:").prefetch_related("lessons__classes", "classes"):
        if rel.classes.exists():
            continue
        classes = {c.pk for lesson in rel.lessons.all() for c in lesson.classes.all()}
        if classes:
            rel.classes.set(classes)


class Migration(migrations.Migration):
    dependencies = [("timetable", "0042_relationship_label")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
