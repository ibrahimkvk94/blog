"""Öğretmenin ünvan ve rütbesi tek alanda: mevcut değerler "ünvan rütbe" sırasıyla birleştirilir."""

from django.db import migrations, models


def merge(apps, schema_editor):
    Teacher = apps.get_model("timetable", "Teacher")
    for t in Teacher.objects.exclude(rank=""):
        t.title = " ".join(filter(None, [t.title.strip(), t.rank.strip()]))[:100]
        t.save(update_fields=["title"])


def split(apps, schema_editor):
    pass  # geri alınırken birleşik değer ünvan alanında kalır


class Migration(migrations.Migration):

    dependencies = [
        ("timetable", "0023_teacher_titles"),
    ]

    operations = [
        migrations.AlterField(
            model_name="teacher",
            name="title",
            field=models.CharField(blank=True, help_text="Ör. Öğr.Gör. Ütğm., Dr., Bnb.", max_length=100, verbose_name="ünvan / rütbe"),
        ),
        migrations.RunPython(merge, split),
        migrations.RemoveField(model_name="teacher", name="rank"),
    ]
