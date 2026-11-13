from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetable', '0045_event'),
    ]

    # Sınav modelleri "sinav" uygulamasına taşındı: tablolar yerinde kalır (sinav.models db_table), burada yalnızca
    # Django'nun model durumundan çıkarılır. Veriye dokunulmaz.
    _moved = [
        migrations.RemoveField(
            model_name='examplacement',
            name='exam',
        ),
        migrations.RemoveField(
            model_name='examperiod',
            name='proctor_exempt',
        ),
        migrations.RemoveField(
            model_name='examperiod',
            name='requested_by',
        ),
        migrations.RemoveField(
            model_name='examperiod',
            name='rooms',
        ),
        migrations.RemoveField(
            model_name='examperiod',
            name='school',
        ),
        migrations.RemoveField(
            model_name='examroom',
            name='placement',
        ),
        migrations.RemoveField(
            model_name='examroom',
            name='classroom',
        ),
        migrations.RemoveField(
            model_name='examroom',
            name='proctors',
        ),
        migrations.DeleteModel(
            name='Exam',
        ),
        migrations.DeleteModel(
            name='ExamPeriod',
        ),
        migrations.DeleteModel(
            name='ExamPlacement',
        ),
        migrations.DeleteModel(
            name='ExamRoom',
        ),
    ]

    operations = [
        migrations.AddField(
            model_name='membership',
            name='modules',
            field=models.JSONField(blank=True, default=list, help_text='Boş = tüm modüller.', verbose_name='modüller'),
        ),
        migrations.SeparateDatabaseAndState(state_operations=_moved),
    ]
