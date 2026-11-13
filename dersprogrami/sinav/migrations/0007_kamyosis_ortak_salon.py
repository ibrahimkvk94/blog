from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("timetable", "0046_sinav_modulu"),
        ("sinav", "0006_kamyosis_oturum_tasiyici"),
    ]

    operations = [
        migrations.AddField(
            model_name="examperiod",
            name="shared_rooms",
            field=models.ManyToManyField(
                blank=True, related_name="+", to="timetable.classroom", verbose_name="ortak salonlar",
                help_text="Aynı oturumda birden çok sınavın birlikte yapılabildiği büyük salonlar (ör. yemekhane); salonun "
                          "sınav kapasitesi o oturumdaki sınavlar arasında bölüşülür. Diğer salonlarda aynı anda tek sınav olur."),
        ),
    ]
