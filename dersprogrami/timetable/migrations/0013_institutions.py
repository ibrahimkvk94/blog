import django.db.models.deletion
from django.db import migrations, models


def to_institutions(apps, schema_editor):
    """Her mevcut okul için aynı adla bir kurum açılır; okul o kurumun programı olur ve
    okul yetkileri kuruma taşınır (yalnızca o programla sınırlı değil: kurumun tek programı zaten odur)."""
    Institution = apps.get_model("timetable", "Institution")
    School = apps.get_model("timetable", "School")
    Membership = apps.get_model("timetable", "Membership")
    for school in School.objects.all():
        institution = Institution.objects.create(name=school.name)
        school.institution = institution
        school.save(update_fields=["institution"])
    for membership in Membership.objects.all():
        membership.institution_id = School.objects.get(pk=membership.school_id).institution_id
        membership.save(update_fields=["institution"])


class Migration(migrations.Migration):
    dependencies = [("timetable", "0012_memberships")]

    operations = [
        migrations.CreateModel(
            name="Institution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, verbose_name="ad")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "kurum", "verbose_name_plural": "kurumlar", "ordering": ["name"]},
        ),
        migrations.AlterModelOptions(name="school", options={"verbose_name": "program", "verbose_name_plural": "programlar"}),
        migrations.AddField(
            model_name="school",
            name="institution",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="programs", to="timetable.institution", verbose_name="kurum"),
        ),
        migrations.AddField(
            model_name="school",
            name="linked_programs",
            field=models.ManyToManyField(blank=True, help_text="Aynı anda yürüyen programlar: bu programların yayındaki programında dolu olan öğretmen (ad soyada göre) ve derslik (ada göre) saatleri burada kapalı sayılır.", to="timetable.school", verbose_name="birlikte çalışan programlar"),
        ),
        migrations.AddField(
            model_name="membership",
            name="institution",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="timetable.institution"),
        ),
        migrations.AddField(
            model_name="membership",
            name="programs",
            field=models.ManyToManyField(blank=True, help_text="Boş = kurumun tüm programları.", related_name="restricted_memberships", to="timetable.school", verbose_name="yalnızca bu programlar"),
        ),
        migrations.RunPython(to_institutions, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="membership", name="unique_membership"),
        migrations.RemoveField(model_name="membership", name="school"),
        migrations.AlterField(
            model_name="membership",
            name="institution",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="timetable.institution"),
        ),
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.UniqueConstraint(fields=("user", "institution"), name="unique_membership"),
        ),
    ]
