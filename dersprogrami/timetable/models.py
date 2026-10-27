"""Ders programı veri modeli.

Temel kavramlar (aSc TimeTables ile aynı mantık):
- Lesson (ders): "ne, kime, kim tarafından, haftada kaç saat" tanımı.
- Card (kart): bir dersin programa yerleştirilmiş tek oturumu (gün + başlangıç saati + derslik).
- Division / Group: sınıfın bölünmesi. Aynı bölünmedeki gruplar aynı anda ders görebilir,
  farklı bölünmelerdeki gruplar çakışır.
- Availability: gün x saat ızgarasında uygun / yasak / koşullu (?) hücreler.
"""

import re

from django.core.exceptions import ValidationError
from django.db import models

DAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class Institution(models.Model):
    """Kurum (okul): altında birbirinden bağımsız ders programları (School) bulunur.

    Ör. "Örnek MYO" kurumunda "2026/2027 1.YY", "2.YY", "Gece öğretimi" programları. Kullanıcı
    yetkileri kurum düzeyindedir (istenirse belirli programlarla sınırlanır).
    """

    name = models.CharField("ad", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "kurum"
        verbose_name_plural = "kurumlar"

    def __str__(self):
        return self.name


class School(models.Model):
    """Bir ders programı (aSc'deki bir program dosyası): kendi saatleri, sınıfları, öğretmenleri,
    dersleri ve üretilmiş sürümleri vardır. Model adı tarihsel olarak School'dur."""

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, null=True, blank=True, related_name="programs", verbose_name="kurum"
    )
    name = models.CharField("ad", max_length=200)
    days_per_week = models.PositiveSmallIntegerField("haftadaki gün sayısı", default=5)
    weeks_count = models.PositiveSmallIntegerField(
        "hafta döngüsü", default=1, help_text="1 = her hafta aynı, 2 = A/B haftası"
    )
    terms_count = models.PositiveSmallIntegerField("dönem sayısı", default=1)
    linked_programs = models.ManyToManyField(
        "self", blank=True, verbose_name="birlikte çalışan programlar",
        help_text="Aynı anda yürüyen programlar: bu programların yayındaki programında dolu olan öğretmen (ad soyada "
        "göre) ve derslik (ada göre) saatleri burada kapalı sayılır.",
    )
    duties_per_teacher = models.PositiveSmallIntegerField(
        "öğretmen başına haftalık nöbet", default=1, help_text="Nöbet dağıtımında öğretmen başına üst sınır (öğretmende ayrıca belirlenebilir)."
    )
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
        verbose_name = "program"
        verbose_name_plural = "programlar"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Her program bir kuruma bağlıdır; kurum verilmezse aynı adla yeni kurum açılır.
        if self.institution_id is None:
            self.institution = Institution.objects.create(name=self.name)
        super().save(*args, **kwargs)

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
    long_break_after = models.BooleanField(
        "ardından uzun teneffüs", default=False, help_text="Blok (çift) dersler bu aranın üzerinden geçemez."
    )

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
    short = models.CharField("kısa ad", max_length=60, blank=True)
    capacity = models.PositiveIntegerField("kapasite", null=True, blank=True)
    building = models.ForeignKey(Building, on_delete=models.SET_NULL, null=True, blank=True)
    max_lessons = models.PositiveSmallIntegerField(
        "aynı anda en fazla ders", default=1,
        help_text="Spor salonu gibi birden çok dersin aynı anda yapılabildiği derslikler için 2 ya da daha fazla.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "derslik"
        verbose_name_plural = "derslikler"

    def __str__(self):
        return self.short or self.name


class Subject(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField("ad", max_length=100)
    short = models.CharField("kısa ad", max_length=60, blank=True)
    color = models.CharField("renk", max_length=7, default="#dfe7fd")
    classrooms = models.ManyToManyField(
        Classroom,
        blank=True,
        related_name="default_for_subjects",
        verbose_name="varsayılan derslikler",
        help_text="Dersliği seçilmemiş bu adlı dersler bu dersliklerden birinde yapılır (ör. Fizik → Fen Lab).",
    )

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
    short = models.CharField("kısa ad", max_length=60, blank=True)
    max_periods_per_day = models.PositiveSmallIntegerField("günde en fazla ders", null=True, blank=True)
    max_gaps_per_day = models.PositiveSmallIntegerField("günde en fazla boşluk", null=True, blank=True)
    max_gaps_per_week = models.PositiveSmallIntegerField("haftada en fazla boşluk", null=True, blank=True)
    max_days_per_week = models.PositiveSmallIntegerField(
        "haftada en fazla gün", null=True, blank=True, help_text="Ör. 4 = haftada bir boş gün"
    )
    max_consecutive = models.PositiveSmallIntegerField(
        "art arda en fazla ders", null=True, blank=True, help_text="Ör. 4 = en fazla 4 saat üst üste"
    )
    min_periods_per_day = models.PositiveSmallIntegerField(
        "geldiği günlerde en az ders", null=True, blank=True, help_text="Ör. 2 = tek saat için okula gelmesin"
    )
    target_periods = models.PositiveSmallIntegerField(
        "haftalık ders yükü (hedef)", null=True, blank=True,
        help_text="Ör. 15 maaş karşılığı + 6 ek ders = 21. Ders dağıtımında eksik/fazla yük gösterilir.",
    )
    subjects = models.ManyToManyField(
        Subject, blank=True, related_name="qualified_teachers", verbose_name="branşlar",
        help_text="Öğretmenin okutabildiği dersler. Branş dışı atamalar uyarı verir; vekil önerisinde önceliklidir.",
    )
    home_classroom = models.ForeignKey(
        Classroom, on_delete=models.SET_NULL, null=True, blank=True, related_name="home_teachers",
        verbose_name="öğretmen dersliği",
        help_text="Dersliği, ders adının ya da sınıfın dersliği belirlenmemiş dersleri bu derslikte yapılır.",
    )
    duty_exempt = models.BooleanField("nöbetten muaf", default=False)
    max_duties = models.PositiveSmallIntegerField(
        "haftada en fazla nöbet", null=True, blank=True, help_text="Boş = okulun genel ayarı"
    )

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "öğretmen"
        verbose_name_plural = "öğretmenler"

    def __str__(self):
        return self.short or self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class SchoolClass(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="classes")
    name = models.CharField("ad", max_length=50)
    short = models.CharField("kısa ad", max_length=30, blank=True, help_text="Ana görünüm ve çıktılarda kullanılır (ör. 1SVN).")
    grade = models.PositiveSmallIntegerField("sınıf seviyesi", null=True, blank=True)
    home_classroom = models.ForeignKey(
        Classroom, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="sınıf dersliği"
    )
    student_count = models.PositiveIntegerField(
        "öğrenci sayısı", null=True, blank=True, help_text="Derslik kapasitesi kontrolü için"
    )
    min_periods_per_day = models.PositiveSmallIntegerField("günde en az ders", null=True, blank=True)
    max_periods_per_day = models.PositiveSmallIntegerField("günde en fazla ders", null=True, blank=True)
    class_teacher = models.ForeignKey(
        Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name="homeroom_classes",
        verbose_name="sınıf öğretmeni", help_text="Çıktılarda sınıf programının başlığında yazar.",
    )

    # Doğal sıralama için: "2.KISIM" "10.KISIM"dan önce gelsin (sayılar sıfırla doldurulur).
    sort_key = models.CharField(max_length=120, blank=True, editable=False)

    class Meta:
        ordering = ["grade", "sort_key", "name"]
        verbose_name = "sınıf"
        verbose_name_plural = "sınıflar"

    def __str__(self):
        return self.name

    @staticmethod
    def natural_key(name):
        return re.sub(r"\d+", lambda m: m.group(0).zfill(8), (name or "").casefold())[:120]

    def save(self, *args, **kwargs):
        self.sort_key = self.natural_key(self.name)
        if kwargs.get("update_fields") is not None and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = list(kwargs["update_fields"]) + ["sort_key"]
        super().save(*args, **kwargs)


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
    classes = models.ManyToManyField(
        SchoolClass, blank=True, related_name="lessons", verbose_name="sınıflar",
        help_text="Boş bırakılırsa ders yalnızca öğretmenleri bağlar (ör. zümre toplantısı, hazırlık saati).",
    )
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
    split = models.CharField(
        "kart dağılımı", max_length=40, blank=True,
        help_text="Ör. 2+2+1 ya da 2+1+1+1. Toplamı haftalık saate eşit olmalı; boşsa kart uzunluğuna göre bölünür.",
    )
    rooms_needed = models.PositiveSmallIntegerField(
        "gereken derslik sayısı", default=1,
        help_text="Ör. iki sınıfın birleşik dersi iki derslikte: 2. Derslikler olası derslikler arasından seçilir.",
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

    @staticmethod
    def parse_split(text):
        """"2+2+1", "2 2 1", "2,2,1" ya da aSc'deki gibi "221" → [2, 2, 1]; geçersizse []."""
        text = (text or "").strip()
        if not text:
            return []
        if text.isdigit():
            parts = list(text)
        else:
            parts = [p for p in text.replace(",", "+").replace(" ", "+").split("+") if p]
        try:
            values = [int(p) for p in parts]
        except ValueError:
            return []
        return values if values and all(v > 0 for v in values) else []

    def card_lengths(self):
        """Haftalık saati kartlara böler: 5 saat / uzunluk 2 → [2, 2, 1]; dağılım girilmişse o kullanılır."""
        parts = self.parse_split(self.split)
        if parts and sum(parts) == self.periods_per_week:
            return sorted(parts, reverse=True)
        length = max(1, self.card_length)
        full, rest = divmod(self.periods_per_week, length)
        return [length] * full + [1] * rest


class Availability(models.Model):
    """Bir varlığın tek bir gün/saat hücresindeki müsaitliği. Kayıt yoksa hücre uygundur.

    Hiçbir hedef seçilmemiş kayıt okul genelidir (ör. Cuma 5. saatten sonra ders yok).
    """

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
        if len(targets) > 1:
            raise ValidationError("En fazla bir hedef (öğretmen, sınıf, derslik, ders adı veya ders) seçilmeli; hedefsiz kayıt tüm okul için geçerlidir.")

    def __str__(self):
        target = next((getattr(self, f) for f in self.TARGET_FIELDS if getattr(self, f + "_id")), "Okul geneli")
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
    # Elle düzenleme geçmişi (geri al / yinele): her adım {"label", "cards": [[id, gün, saat, derslik, ek derslikler, kilit]]}
    history = models.JSONField(default=list, blank=True)
    redo_stack = models.JSONField(default=list, blank=True)

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
    # Birden çok derslik isteyen derslerde ana derslik dışındaki derslikler (kimlik listesi).
    extra_rooms = models.JSONField(default=list, blank=True)
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

    @property
    def room_ids(self):
        return ([self.classroom_id] if self.classroom_id else []) + [r for r in self.extra_rooms or [] if r != self.classroom_id]

    def covers(self, day, period):
        return self.is_placed and self.day == day and self.period <= period < self.period + self.length


class TimetableVersion(models.Model):
    """Programın kayıtlı bir hali (aSc "Versiyonlar"): kart konumlarının anlık görüntüsü."""

    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField("no")
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="hazırlayan")
    note = models.CharField("not", max_length=200, blank=True)
    auto = models.BooleanField("otomatik kayıt", default=False)
    changes = models.PositiveIntegerField("değişen kart", default=0)
    cards = models.JSONField(default=list)  # [[kart, gün, saat, derslik, ek derslikler, kilit], ...]

    class Meta:
        ordering = ["-number"]
        verbose_name = "program versiyonu"
        verbose_name_plural = "program versiyonları"
        constraints = [models.UniqueConstraint(fields=["timetable", "number"], name="unique_version_number")]

    def __str__(self):
        return f"{self.timetable} #{self.number}"


class CardRelationship(models.Model):
    """Seçilen kartlara toplu uygulanan kural (aSc'deki "kart ilişkileri").

    Kart kümesi: seçilen dersler ve/veya ders adları; sınıf ve öğretmen seçimi kümeyi daraltır,
    kart uzunluğu filtresi yalnızca tekil ya da blok kartları bırakır. "Uygula" alanı kümeyi
    parçalara böler: ör. "her sınıf için ayrı" seçilirse kural her sınıfın kartlarına ayrı ayrı
    uygulanır. Zaman haritası (gün × saat hücreleri) seçilirse harita kullanan koşullar yalnızca
    işaretli hücrelerdeki dersleri sayar. İki taraflı koşullarda B tarafı ayrıca seçilir.
    """

    MAX_PER_DAY = "max_per_day"
    DIFFERENT_DAYS = "different_days"
    MIN_GAP_DAYS = "min_gap_days"
    MAX_DAYS = "max_days"
    MIN_DAYS = "min_days"
    RANGE_MAX_PER_DAY = "range_max_per_day"
    RANGE_MAX_DAYS = "range_max_days"
    MAP_MAX_WEEK = "map_max_week"
    MAP_MIN_WEEK = "map_min_week"
    MAP_MIN_IF_ANY = "map_min_if_any"
    MAX_CONSECUTIVE = "max_consecutive"
    MAX_GAPS_PER_DAY = "max_gaps_per_day"
    MAX_GAP_LENGTH = "max_gap_length"
    MAX_DISTINCT_PERIODS = "max_distinct_periods"
    MAX_SAME_PERIOD_DAYS = "max_same_period_days"
    NOT_SIMULTANEOUS = "not_simultaneous"
    MAX_PER_POSITION = "max_per_position"
    MIN_PER_POSITION = "min_per_position"
    SAME_TIME = "same_time"
    SAME_DAY = "same_day"
    CONSECUTIVE = "consecutive"
    CONSECUTIVE_ORDERED = "consecutive_ordered"
    AB_NOT_SAME_DAY = "ab_not_same_day"
    AB_NOT_CONSECUTIVE = "ab_not_consecutive"
    AB_NOT_DAY_AFTER = "ab_not_day_after"
    ROOM_MAX_WEEK = "room_max_week"
    ROOM_MIN_WEEK = "room_min_week"
    MAX_ROOMS_WEEK = "max_rooms_week"
    MAX_BUILDINGS_DAY = "max_buildings_day"
    CONDITION_CHOICES = [
        ("Haftalık dağılım", [
            (MAX_PER_DAY, "Günde en fazla N kart"),
            (DIFFERENT_DAYS, "Farklı günlerde"),
            (MIN_GAP_DAYS, "Kartlar arasında en az N boş gün"),
            (MAX_DAYS, "Haftada en fazla N güne yayılsın"),
            (MIN_DAYS, "Haftada en az N güne yayılsın"),
        ]),
        ("İşaretli saatler (zaman haritası)", [
            (RANGE_MAX_PER_DAY, "İşaretli saatlerde günde en fazla N saat"),
            (RANGE_MAX_DAYS, "İşaretli saatlerde ders olan en fazla N gün"),
            (MAP_MAX_WEEK, "İşaretli saatlerde haftada en fazla N saat"),
            (MAP_MIN_WEEK, "İşaretli saatlerde haftada en az N saat"),
            (MAP_MIN_IF_ANY, "İşaretli saatlerde ders varsa en az N saat (boş gün olabilir)"),
        ]),
        ("Art arda ve boşluklar", [
            (MAX_CONSECUTIVE, "Art arda en fazla N saat"),
            (MAX_GAPS_PER_DAY, "Günde en fazla N boş saat"),
            (MAX_GAP_LENGTH, "En fazla N saatlik boşluk"),
        ]),
        ("Saatlere yayılım", [
            (MAX_DISTINCT_PERIODS, "Hafta boyunca en fazla N farklı saatte (N=1: her gün aynı saat)"),
            (MAX_SAME_PERIOD_DAYS, "Aynı saate en fazla N gün"),
        ]),
        ("Eşzamanlılık", [
            (NOT_SIMULTANEOUS, "Aynı anda olmasın"),
            (MAX_PER_POSITION, "Her saatte en fazla N kart"),
            (MIN_PER_POSITION, "İşaretli her saatte en az N kart"),
        ]),
        ("Seçilen derslerin eşleşen kartları", [
            (SAME_TIME, "Aynı anda"),
            (SAME_DAY, "Aynı gün"),
            (CONSECUTIVE, "Art arda, bitişik (sıra serbest)"),
            (CONSECUTIVE_ORDERED, "Art arda, sıralı (önce ilk seçilen ders)"),
        ]),
        ("İki taraflı (A ↔ B)", [
            (AB_NOT_SAME_DAY, "A ile B aynı gün olmasın"),
            (AB_NOT_CONSECUTIVE, "A ile B art arda olmasın"),
            (AB_NOT_DAY_AFTER, "B, A'dan sonraki gün olmasın"),
        ]),
        ("Derslik ve bina", [
            (ROOM_MAX_WEEK, "Seçili dersliklerde haftada en fazla N saat"),
            (ROOM_MIN_WEEK, "Seçili dersliklerde haftada en az N saat"),
            (MAX_ROOMS_WEEK, "Haftada en fazla N farklı derslik"),
            (MAX_BUILDINGS_DAY, "Günde en fazla N farklı bina"),
        ]),
    ]
    # Seçilen derslerin i. kartlarını eşleştiren koşullar (her ders bir küme).
    PAIRED = {SAME_TIME, SAME_DAY, CONSECUTIVE, CONSECUTIVE_ORDERED}
    TWO_SIDED = {AB_NOT_SAME_DAY, AB_NOT_CONSECUTIVE, AB_NOT_DAY_AFTER}
    ROOMS = {ROOM_MAX_WEEK, ROOM_MIN_WEEK}
    USES_N = {
        MAX_PER_DAY, MIN_GAP_DAYS, MAX_DAYS, MIN_DAYS, RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK,
        MAP_MIN_WEEK, MAP_MIN_IF_ANY, MAX_CONSECUTIVE, MAX_GAPS_PER_DAY, MAX_GAP_LENGTH, MAX_DISTINCT_PERIODS,
        MAX_SAME_PERIOD_DAYS, MAX_PER_POSITION, MIN_PER_POSITION, ROOM_MAX_WEEK, ROOM_MIN_WEEK, MAX_ROOMS_WEEK,
        MAX_BUILDINGS_DAY,
    }
    # Zaman haritasını kullanan koşullar (harita boşsa tüm hücreler sayılır).
    USES_MAP = {
        MAX_DAYS, RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK, MAP_MIN_WEEK, MAP_MIN_IF_ANY, MAX_PER_POSITION,
        MIN_PER_POSITION, AB_NOT_SAME_DAY, AB_NOT_DAY_AFTER, ROOM_MAX_WEEK, ROOM_MIN_WEEK,
    }
    NEEDS_MAP = {RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK, MAP_MIN_WEEK, MAP_MIN_IF_ANY, MIN_PER_POSITION}

    ALL = "all"
    EACH_CLASS = "each_class"
    EACH_TEACHER = "each_teacher"
    EACH_SUBJECT_CLASS = "each_subject_class"
    EACH_TEACHER_CLASS = "each_teacher_class"
    EACH_GROUP = "each_group"
    EACH_GRADE = "each_grade"
    APPLY_CHOICES = [
        (ALL, "Tüm seçime birlikte"),
        (EACH_CLASS, "Her sınıf için ayrı"),
        (EACH_TEACHER, "Her öğretmen için ayrı"),
        (EACH_SUBJECT_CLASS, "Her sınıfta her ders adı için ayrı"),
        (EACH_TEACHER_CLASS, "Her öğretmenin her sınıfı için ayrı"),
        (EACH_GROUP, "Her öğrenci grubu için ayrı"),
        (EACH_GRADE, "Her sınıf seviyesi için ayrı"),
    ]

    STRICT = "strict"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    IMPORTANCE_CHOICES = [(STRICT, "Kesin"), (HIGH, "Yüksek"), (NORMAL, "Normal"), (LOW, "Düşük")]
    WEIGHTS = {HIGH: 300, NORMAL: 60, LOW: 15}

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="relationships")
    name = models.CharField("ad", max_length=200)
    active = models.BooleanField("etkin", default=True)
    condition = models.CharField("koşul", max_length=24, choices=CONDITION_CHOICES, default=MAX_PER_DAY)
    param = models.PositiveSmallIntegerField("N", default=1)
    time_map = models.JSONField("zaman haritası", default=list, blank=True, help_text='"gün-saat" listesi (0\'dan başlar)')
    time_map_b = models.JSONField("B tarafı zaman haritası", default=list, blank=True)
    card_length = models.PositiveSmallIntegerField(
        "kart uzunluğu", null=True, blank=True, choices=[(1, "Yalnızca tekil kartlar"), (2, "Yalnızca 2 saatlik bloklar"), (3, "Yalnızca 3 saatlik bloklar")]
    )
    apply_to = models.CharField("uygula", max_length=20, choices=APPLY_CHOICES, default=EACH_CLASS)
    importance = models.CharField("önem", max_length=10, choices=IMPORTANCE_CHOICES, default=STRICT)
    lessons = models.ManyToManyField(Lesson, blank=True, related_name="relationships", verbose_name="dersler")
    subjects = models.ManyToManyField(Subject, blank=True, related_name="relationships", verbose_name="ders adları")
    lessons_b = models.ManyToManyField(Lesson, blank=True, related_name="relationships_b", verbose_name="B tarafı: dersler")
    subjects_b = models.ManyToManyField(Subject, blank=True, related_name="relationships_b", verbose_name="B tarafı: ders adları")
    classes = models.ManyToManyField(SchoolClass, blank=True, related_name="relationships", verbose_name="yalnızca bu sınıflar")
    teachers = models.ManyToManyField(Teacher, blank=True, related_name="relationships", verbose_name="yalnızca bu öğretmenler")
    classrooms = models.ManyToManyField(Classroom, blank=True, related_name="relationships", verbose_name="derslikler")

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


class DutyPlace(models.Model):
    """Nöbet yeri (aSc'de "room supervision" alanı): ör. Bahçe, 1. kat koridoru."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="duty_places")
    name = models.CharField("ad", max_length=100)
    teachers_per_day = models.PositiveSmallIntegerField("günlük nöbetçi sayısı", default=1)
    days = models.JSONField("nöbet günleri", default=list, blank=True, help_text="Boş = okulun tüm günleri")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "nöbet yeri"
        verbose_name_plural = "nöbet yerleri"

    def __str__(self):
        return self.name

    def active_days(self):
        days = range(self.school.days_per_week)
        return [d for d in days if not self.days or d in self.days]


class Duty(models.Model):
    """Bir öğretmenin bir günde bir nöbet yerindeki görevi."""

    place = models.ForeignKey(DutyPlace, on_delete=models.CASCADE, related_name="duties")
    day = models.PositiveSmallIntegerField("gün")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="duties")

    class Meta:
        ordering = ["day", "place__order", "id"]
        verbose_name = "nöbet"
        verbose_name_plural = "nöbetler"
        constraints = [models.UniqueConstraint(fields=["place", "day", "teacher"], name="unique_duty")]

    def __str__(self):
        return f"{self.teacher} – {self.place} ({DAY_NAMES[self.day]})"


class ReportPreset(models.Model):
    """Kaydedilmiş rapor ayarı (aSc "baskı tasarımı" karşılığı): rapor türü ve tüm seçenekler."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="report_presets")
    name = models.CharField("ad", max_length=100)
    params = models.JSONField(default=dict)

    class Meta:
        ordering = ["name"]
        verbose_name = "rapor şablonu"
        verbose_name_plural = "rapor şablonları"

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Kullanıcının bir kurumdaki yetkileri. Merkez yönetici (süper kullanıcı) tüm kurumlara erişir."""

    VIEW = "goruntule"
    DATA = "veri"
    PROGRAM = "program"
    PUBLISH = "yayin"
    SUBSTITUTE = "vekalet"
    DUTY = "nobet"
    USERS = "kullanici"
    PROGRAMS = "programlar"
    PERMISSIONS = [
        (VIEW, "Görüntüleme ve raporlar"),
        (DATA, "Veri girişi (sınıf, öğretmen, ders, kart ilişkileri)"),
        (PROGRAM, "Program üretme ve düzenleme"),
        (PUBLISH, "Programı yayınlama"),
        (SUBSTITUTE, "Vekâlet işlemleri"),
        (DUTY, "Nöbet çizelgesi"),
        (PROGRAMS, "Program ekleme, aSc'den içe aktarma ve silme"),
        (USERS, "Kullanıcı yönetimi (kendi yetkileri kadar)"),
    ]
    ALL = [key for key, _ in PERMISSIONS]

    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="memberships")
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="memberships")
    permissions = models.JSONField("yetkiler", default=list)
    programs = models.ManyToManyField(
        School, blank=True, related_name="restricted_memberships", verbose_name="yalnızca bu programlar",
        help_text="Boş = kurumun tüm programları.",
    )
    granted_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="granted_memberships"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username"]
        verbose_name = "okul yetkisi"
        verbose_name_plural = "okul yetkileri"
        constraints = [models.UniqueConstraint(fields=["user", "institution"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} @ {self.institution}"

    @property
    def perms(self):
        return set(self.permissions) | {self.VIEW}

    def labels(self):
        names = dict(self.PERMISSIONS)
        return [names[p] for p in self.ALL if p in self.perms]
