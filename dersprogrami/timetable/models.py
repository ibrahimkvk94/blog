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
    active_timetable = models.ForeignKey(
        "Timetable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="yayındaki program",
        help_text="Vekâlet işlemlerinde esas alınan program.",
    )

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
    max_days_per_week = models.PositiveSmallIntegerField(
        "haftada en fazla gün", null=True, blank=True, help_text="Ör. 4 = haftada bir boş gün"
    )

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
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    STATUS_CHOICES = [
        (DRAFT, "Taslak"),
        (RUNNING, "Üretiliyor"),
        (OK, "Üretildi"),
        (PARTIAL, "Kısmen üretildi"),
        (FAILED, "Üretilemedi"),
    ]

    STRICT = "strict"
    RELAXED = "relaxed"
    MODE_CHOICES = [(STRICT, "Katı"), (RELAXED, "Gevşek (taslak)")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="timetables")
    name = models.CharField("ad", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    mode = models.CharField("üretim modu", max_length=10, choices=MODE_CHOICES, default=STRICT)
    time_limit = models.PositiveIntegerField("süre sınırı (sn)", default=60)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    objective = models.IntegerField("ceza puanı", null=True, blank=True)
    report = models.JSONField("rapor", default=dict, blank=True)

    @property
    def has_grid(self):
        return self.status in (self.OK, self.PARTIAL, self.DRAFT)

    @property
    def is_running(self):
        return self.status == self.RUNNING

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


class CardRelationship(models.Model):
    """Seçilen kartlara toplu uygulanan kural (aSc'deki "kart ilişkileri").

    Kart kümesi: seçilen dersler ve/veya ders adları; sınıf ve öğretmen seçimi kümeyi daraltır.
    "Uygula" alanı kümeyi parçalara böler: ör. "her sınıf için ayrı" seçilirse kural her sınıfın
    kartlarına ayrı ayrı uygulanır.
    """

    MAX_PER_DAY = "max_per_day"
    DIFFERENT_DAYS = "different_days"
    MAX_CONSECUTIVE = "max_consecutive"
    SAME_TIME = "same_time"
    CONDITION_CHOICES = [
        (MAX_PER_DAY, "Günde en fazla N kart"),
        (DIFFERENT_DAYS, "Farklı günlerde"),
        (MAX_CONSECUTIVE, "Art arda en fazla N saat"),
        (SAME_TIME, "Aynı anda (seçilen dersler)"),
    ]

    ALL = "all"
    EACH_CLASS = "each_class"
    EACH_TEACHER = "each_teacher"
    APPLY_CHOICES = [(ALL, "Tüm seçime birlikte"), (EACH_CLASS, "Her sınıf için ayrı"), (EACH_TEACHER, "Her öğretmen için ayrı")]

    STRICT = "strict"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    IMPORTANCE_CHOICES = [(STRICT, "Kesin"), (HIGH, "Yüksek"), (NORMAL, "Normal"), (LOW, "Düşük")]
    WEIGHTS = {HIGH: 300, NORMAL: 60, LOW: 15}

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="relationships")
    name = models.CharField("ad", max_length=200)
    active = models.BooleanField("etkin", default=True)
    condition = models.CharField("koşul", max_length=20, choices=CONDITION_CHOICES, default=MAX_PER_DAY)
    param = models.PositiveSmallIntegerField("N", default=1)
    apply_to = models.CharField("uygula", max_length=20, choices=APPLY_CHOICES, default=EACH_CLASS)
    importance = models.CharField("önem", max_length=10, choices=IMPORTANCE_CHOICES, default=STRICT)
    lessons = models.ManyToManyField(Lesson, blank=True, related_name="relationships", verbose_name="dersler")
    subjects = models.ManyToManyField(Subject, blank=True, related_name="relationships", verbose_name="ders adları")
    classes = models.ManyToManyField(SchoolClass, blank=True, related_name="relationships", verbose_name="yalnızca bu sınıflar")
    teachers = models.ManyToManyField(Teacher, blank=True, related_name="relationships", verbose_name="yalnızca bu öğretmenler")

    class Meta:
        verbose_name = "kart ilişkisi"
        verbose_name_plural = "kart ilişkileri"

    def __str__(self):
        return self.name

    @property
    def weight(self):
        """None = sert kısıt."""
        return self.WEIGHTS.get(self.importance)


class Absence(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="absences")
    date = models.DateField("tarih")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="absences", verbose_name="öğretmen")
    reason = models.CharField("neden", max_length=200, blank=True)

    class Meta:
        ordering = ["date", "teacher"]
        unique_together = [("date", "teacher")]
        verbose_name = "devamsızlık"
        verbose_name_plural = "devamsızlıklar"

    def __str__(self):
        return f"{self.teacher} – {self.date:%d.%m.%Y}"


class Substitution(models.Model):
    """Devamsız öğretmenin tek bir ders saatine atanan vekil öğretmen."""

    absence = models.ForeignKey(Absence, on_delete=models.CASCADE, related_name="substitutions")
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="substitutions")
    period = models.PositiveSmallIntegerField("saat")
    substitute = models.ForeignKey(
        Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name="substitutions", verbose_name="vekil"
    )
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        ordering = ["period"]
        unique_together = [("absence", "card", "period")]
        verbose_name = "vekâlet"
        verbose_name_plural = "vekâletler"

    def __str__(self):
        return f"{self.absence} – {self.period + 1}. saat → {self.substitute or 'boş'}"
