"""Ders programı veri modeli.

Temel kavramlar (aSc TimeTables ile aynı mantık):
- Lesson (ders): "ne, kime, kim tarafından, haftada kaç saat" tanımı.
- Card (kart): bir dersin programa yerleştirilmiş tek oturumu (gün + başlangıç saati + derslik).
- Division / Group: sınıfın bölünmesi. Aynı bölünmedeki gruplar aynı anda ders görebilir,
  farklı bölünmelerdeki gruplar çakışır.
- Availability: gün x saat ızgarasında uygun / yasak / koşullu (?) hücreler.
"""

from django.core.exceptions import ValidationError
from django.db import models

DAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class School(models.Model):
    name = models.CharField("ad", max_length=200)
    days_per_week = models.PositiveSmallIntegerField("haftadaki gün sayısı", default=5)
    weeks_count = models.PositiveSmallIntegerField(
        "hafta döngüsü", default=1, help_text="1 = her hafta aynı, 2 = A/B haftası"
    )
    terms_count = models.PositiveSmallIntegerField("dönem sayısı", default=1)

    class Meta:
        verbose_name = "okul"
        verbose_name_plural = "okullar"

    def __str__(self):
        return self.name

    def clean(self):
        if not 1 <= self.days_per_week <= len(DAY_NAMES):
            raise ValidationError({"days_per_week": "Gün sayısı 1 ile 7 arasında olmalı."})

    @property
    def day_names(self):
        return DAY_NAMES[: self.days_per_week]


class Period(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="periods")
    index = models.PositiveSmallIntegerField("sıra", help_text="0'dan başlar")
    name = models.CharField("ad", max_length=50)
    start_time = models.TimeField("başlangıç", null=True, blank=True)
    end_time = models.TimeField("bitiş", null=True, blank=True)

    class Meta:
        ordering = ["school", "index"]
        unique_together = [("school", "index")]
        verbose_name = "ders saati"
        verbose_name_plural = "ders saatleri"

    def __str__(self):
        return self.name


class Building(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="buildings")
    name = models.CharField("ad", max_length=100)

    class Meta:
        verbose_name = "bina"
        verbose_name_plural = "binalar"

    def __str__(self):
        return self.name


class Classroom(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classrooms")
    name = models.CharField("ad", max_length=100)
    short = models.CharField("kısa ad", max_length=20, blank=True)
    capacity = models.PositiveIntegerField("kapasite", null=True, blank=True)
    building = models.ForeignKey(Building, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "derslik"
        verbose_name_plural = "derslikler"

    def __str__(self):
        return self.short or self.name


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField("ad", max_length=100)
    short = models.CharField("kısa ad", max_length=20, blank=True)
    color = models.CharField("renk", max_length=7, default="#dfe7fd")

    class Meta:
        ordering = ["name"]
        verbose_name = "ders adı"
        verbose_name_plural = "ders adları"

    def __str__(self):
        return self.short or self.name


class Teacher(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="teachers")
    first_name = models.CharField("ad", max_length=100)
    last_name = models.CharField("soyad", max_length=100)
    short = models.CharField("kısa ad", max_length=20, blank=True)
    max_periods_per_day = models.PositiveSmallIntegerField("günde en fazla ders", null=True, blank=True)
    max_gaps_per_day = models.PositiveSmallIntegerField("günde en fazla boşluk", null=True, blank=True)
    max_gaps_per_week = models.PositiveSmallIntegerField("haftada en fazla boşluk", null=True, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "öğretmen"
        verbose_name_plural = "öğretmenler"

    def __str__(self):
        return self.short or f"{self.first_name} {self.last_name}"


class SchoolClass(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField("ad", max_length=50)
    grade = models.PositiveSmallIntegerField("sınıf seviyesi", null=True, blank=True)
    home_classroom = models.ForeignKey(
        Classroom, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="sınıf dersliği"
    )

    class Meta:
        ordering = ["grade", "name"]
        verbose_name = "sınıf"
        verbose_name_plural = "sınıflar"

    def __str__(self):
        return self.name


class Division(models.Model):
    """Sınıfı tamamen kapsayan grupların kümesi (ör. Kız/Erkek, Almanca/Fransızca)."""

    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, related_name="divisions")
    name = models.CharField("ad", max_length=50)

    class Meta:
        verbose_name = "bölünme"
        verbose_name_plural = "bölünmeler"

    def __str__(self):
        return f"{self.school_class} / {self.name}"


class Group(models.Model):
    division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name="groups")
    name = models.CharField("ad", max_length=50)
    student_count = models.PositiveIntegerField("öğrenci sayısı", null=True, blank=True)

    class Meta:
        verbose_name = "grup"
        verbose_name_plural = "gruplar"

    def __str__(self):
        return f"{self.division.school_class} {self.name}"

    @property
    def school_class(self):
        return self.division.school_class


class Lesson(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="lessons")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="ders adı")
    classes = models.ManyToManyField(SchoolClass, related_name="lessons", verbose_name="sınıflar")
    groups = models.ManyToManyField(
        Group,
        blank=True,
        related_name="lessons",
        verbose_name="gruplar",
        help_text="Boş bırakılan sınıflar için ders tüm sınıfa verilir.",
    )
    teachers = models.ManyToManyField(Teacher, blank=True, related_name="lessons", verbose_name="öğretmenler")
    classrooms = models.ManyToManyField(
        Classroom,
        blank=True,
        related_name="lessons",
        verbose_name="olası derslikler",
        help_text="Boşsa ve ders tek sınıfa aitse sınıf dersliği kullanılır.",
    )
    periods_per_week = models.PositiveSmallIntegerField("haftalık saat", default=1)
    card_length = models.PositiveSmallIntegerField(
        "kart uzunluğu", default=1, help_text="1 = tekil ders, 2 = blok (çift) ders"
    )
    max_per_day = models.PositiveSmallIntegerField(
        "günde en fazla kart",
        null=True,
        blank=True,
        help_text="Boşsa kartlar mümkün olduğunca farklı günlere dağıtılır.",
    )
    weeks_mask = models.PositiveIntegerField(
        "haftalar (bit maskesi)", null=True, blank=True, help_text="Boş = her hafta. 1 = A haftası, 2 = B haftası."
    )
    terms_mask = models.PositiveIntegerField("dönemler (bit maskesi)", null=True, blank=True, help_text="Boş = tüm dönemler.")

    class Meta:
        verbose_name = "ders"
        verbose_name_plural = "dersler"

    def __str__(self):
        classes = ", ".join(str(c) for c in self.classes.all())
        return f"{self.subject} – {classes} ({self.periods_per_week} saat)"

    def card_lengths(self):
        """Haftalık saati kartlara böler: 5 saat / uzunluk 2 → [2, 2, 1]."""
        length = max(1, self.card_length)
        full, rest = divmod(self.periods_per_week, length)
        return [length] * full + [1] * rest


class Availability(models.Model):
    """Bir varlığın tek bir gün/saat hücresindeki müsaitliği. Kayıt yoksa hücre uygundur."""

    NO = "no"
    MAYBE = "maybe"
    STATE_CHOICES = [(NO, "Yasak"), (MAYBE, "Koşullu (?)")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="availabilities")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, null=True, blank=True, related_name="availabilities")
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, null=True, blank=True, related_name="availabilities"
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, null=True, blank=True, related_name="availabilities")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, null=True, blank=True, related_name="availabilities")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, null=True, blank=True, related_name="availabilities")
    day = models.PositiveSmallIntegerField("gün", help_text="0 = Pazartesi")
    period = models.PositiveSmallIntegerField("saat", help_text="Ders saatinin sırası (0'dan başlar)")
    state = models.CharField("durum", max_length=5, choices=STATE_CHOICES, default=NO)

    TARGET_FIELDS = ("teacher", "school_class", "classroom", "subject", "lesson")

    class Meta:
        verbose_name = "müsaitlik"
        verbose_name_plural = "müsaitlikler"

    def clean(self):
        targets = [f for f in self.TARGET_FIELDS if getattr(self, f + "_id")]
        if len(targets) != 1:
            raise ValidationError("Tam olarak bir hedef (öğretmen, sınıf, derslik, ders adı veya ders) seçilmeli.")

    def __str__(self):
        target = next((getattr(self, f) for f in self.TARGET_FIELDS if getattr(self, f + "_id")), "?")
        return f"{target}: gün {self.day + 1}, saat {self.period + 1} = {self.get_state_display()}"


class Timetable(models.Model):
    """Bir üretim sonucu (sürüm). Kullanıcı sürümleri karşılaştırıp birini seçebilir."""

    DRAFT = "draft"
    OK = "ok"
    FAILED = "failed"
    STATUS_CHOICES = [(DRAFT, "Taslak"), (OK, "Üretildi"), (FAILED, "Üretilemedi")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="timetables")
    name = models.CharField("ad", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    objective = models.IntegerField("ceza puanı", null=True, blank=True)
    report = models.JSONField("rapor", default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "program"
        verbose_name_plural = "programlar"

    def __str__(self):
        return f"{self.school} – {self.name}"


class Card(models.Model):
    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE, related_name="cards")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="cards")
    length = models.PositiveSmallIntegerField(default=1)
    day = models.PositiveSmallIntegerField(null=True, blank=True)
    period = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Başlangıç saati")
    classroom = models.ForeignKey(Classroom, on_delete=models.SET_NULL, null=True, blank=True)
    locked = models.BooleanField("kilitli", default=False)

    class Meta:
        verbose_name = "kart"
        verbose_name_plural = "kartlar"

    def __str__(self):
        if self.day is None:
            return f"{self.lesson} (yerleşmedi)"
        return f"{self.lesson} @ gün {self.day + 1}, saat {self.period + 1}"

    @property
    def is_placed(self):
        return self.day is not None and self.period is not None

    def covers(self, day, period):
        return self.is_placed and self.day == day and self.period <= period < self.period + self.length
