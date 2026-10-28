"""Ders programı veri modeli.

Temel kavramlar (aSc TimeTables ile aynı mantık):
- Lesson (ders): "ne, kime, kim tarafından, haftada kaç saat" tanımı.
- Card (kart): bir dersin programa yerleştirilmiş tek oturumu (gün + başlangıç saati + derslik).
- Division / Group: sınıfın bölünmesi. Aynı bölünmedeki gruplar aynı anda ders görebilir,
  farklı bölünmelerdeki gruplar çakışır.
- Availability: gün x saat ızgarasında uygun / yasak / koşullu (?) hücreler.
"""

import datetime
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
    publish_token = models.CharField("web yayını anahtarı", max_length=40, blank=True, db_index=True)
    publish_enabled = models.BooleanField("web yayını açık", default=False)
    publish_teachers = models.BooleanField("yayında öğretmen adlarını göster", default=True)
    publish_substitutions = models.BooleanField("yayında vekâlet ekranı", default=True)
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
    # Programın verisi (ders, öğretmen, müsaitlik, ilişki…) her değiştiğinde artar; çözücü problemi
    # önbelleği bununla geçersiz kılınır (bkz. problem_cache.py).
    data_version = models.PositiveIntegerField(default=0, editable=False)
    # ÜYBS aktarım şablonu ayarları: sabit sütunlar, ders kodu öneki eşlemesi, ref sütunu (bkz. uybs.py).
    uybs_settings = models.JSONField("ÜYBS ayarları", default=dict, blank=True)

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
    # Günlere göre farklı saat: {"4": ["08:00", "08:35"]} (gün sırası → başlangıç, bitiş). Olmayan gün varsayılanı kullanır.
    day_times = models.JSONField("günlere göre saatler", default=dict, blank=True)

    class Meta:
        ordering = ["school", "index"]
        unique_together = [("school", "index")]
        verbose_name = "ders saati"
        verbose_name_plural = "ders saatleri"

    def __str__(self):
        return self.name

    def times(self, day=None):
        """(başlangıç, bitiş) o gün için; güne özel saat yoksa varsayılan."""
        override = (self.day_times or {}).get(str(day)) if day is not None else None
        if override:
            try:
                return datetime.time.fromisoformat(override[0]), datetime.time.fromisoformat(override[1])
            except (ValueError, IndexError, TypeError):
                pass
        return self.start_time, self.end_time

    def span(self, day=None):
        start, end = self.times(day)
        return f"{start:%H:%M}–{end:%H:%M}" if start and end else ""


def day_time_notes(periods, day_names):
    """Varsayılandan farklı saatli günler için dipnot satırları: ["Cuma: 1. 08:00–08:35 · 2. …"]."""
    notes = []
    for day, name in enumerate(day_names):
        parts = [f"{p.index + 1}. {p.span(day)}" for p in periods if str(day) in (p.day_times or {})]
        if parts:
            notes.append(f"{name}: " + " · ".join(parts))
    return notes


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
    department = models.CharField("bölüm", max_length=60, blank=True, help_text="Raporlarda adın önüne yazılabilir (ör. ELN).")
    title = models.CharField("ünvan / rütbe", max_length=100, blank=True, help_text="Ör. Öğr.Gör. Ütğm., Dr., Bnb.")
    tc_no = models.CharField("TC kimlik no", max_length=11, blank=True, help_text="ÜYBS aktarımında öğretim elemanı sütununa yazılır.")
    email = models.EmailField("e-posta", blank=True, help_text="Program değişikliği ve vekâlet bildirimleri için.")
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="teacher_profiles",
        verbose_name="kullanıcı hesabı",
        help_text="Bu hesapla giren öğretmen “İsteklerim” sayfasından gelemeyeceği saatleri bildirir.",
    )
    # Telefon takvimi aboneliği için gizli anahtar (giriş gerektirmeyen .ics bağlantısı); boşsa kapalı.
    calendar_token = models.CharField(max_length=40, blank=True, db_index=True, editable=False)

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "öğretmen"
        verbose_name_plural = "öğretmenler"

    def __str__(self):
        return self.short or self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def label(self, parts=("bolum", "unvan")):
        """Raporlarda: seçilen künye bilgileri + ad soyad (ör. "ELN Öğr.Gör. Ütğm. Ali Kaya")."""
        values = {"bolum": self.department, "unvan": self.title}
        return " ".join(filter(None, [values[p] for p in ("bolum", "unvan") if p in parts] + [self.full_name]))


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
    uybs_no = models.CharField(
        "ÜYBS kısım no", max_length=20, blank=True, help_text="Boşsa adın başındaki sayı kullanılır (ör. 1.KISIM → 1)."
    )

    # Doğal sıralama için: "2.KISIM" "10.KISIM"dan önce gelsin (sayılar sıfırla doldurulur).
    sort_key = models.CharField(max_length=120, blank=True, editable=False)

    class Meta:
        ordering = ["grade", "sort_key", "name"]
        verbose_name = "sınıf"
        verbose_name_plural = "sınıflar"

    def __str__(self):
        return self.name

    def number_label(self):
        """Yalnızca numara: "70.KISIM" → "70"; numarasızsa sözcük baş harfleri + numara ("Hazırlık 1" → "H1",
        "Kr.Tm.İşl." → "KTİ")."""
        m = re.match(r"\s*(\d+)", self.name or "") or re.match(r"\s*(\d+)", self.short or "")
        if m:
            return m[1]
        words = re.findall(r"[^\W\d_]+", self.name or "", re.UNICODE)
        digits = "".join(re.findall(r"\d+", self.name or ""))
        initials = "".join(w[0].upper() if w[0] != "i" else "İ" for w in words)
        return (initials + digits) or (self.short or self.name)

    @staticmethod
    def sort_key_of(name):
        return re.sub(r"\d+", lambda m: m.group(0).zfill(8), (name or "").casefold())[:120]

    def save(self, *args, **kwargs):
        self.sort_key = self.sort_key_of(self.name)
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
    teacher_locked = models.BooleanField(
        "öğretmeni sabit", default=False,
        help_text="Ders adının öğretmen kotası varsa üretim kilitsiz kısımların öğretmenini kotaya göre kendisi seçer; "
                  "işaretliyse bu kısmın öğretmeni değişmez.",
    )
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
    elective = models.BooleanField(
        "seçmeli ders", default=False,
        help_text="Öğrenciler seçimlerine göre bu derse (şubeye) dağıtılır; aynı öğrencinin dersleri çakışmaz.",
    )
    capacity = models.PositiveSmallIntegerField("kontenjan", null=True, blank=True, help_text="Seçmeli dersin en fazla öğrenci sayısı.")
    students = models.ManyToManyField("Student", blank=True, related_name="lessons", verbose_name="kayıtlı öğrenciler")

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


class LeaveRequest(models.Model):
    """Öğretmenin tarihli izin/rapor bildirimi. Onaylanınca aralıktaki her okul günü için devamsızlık
    (Absence) yazılır ve dersler vekâlet ekranına düşer; kalıcı müsaitlik değişmez."""

    KINDS = [("rapor", "Rapor"), ("izin", "İzin"), ("gorev", "Görevlendirme"), ("diger", "Diğer")]
    PENDING, APPROVED, REJECTED, WITHDRAWN = "bekliyor", "onaylandi", "reddedildi", "geri_alindi"
    STATUS_CHOICES = [(PENDING, "Bekliyor"), (APPROVED, "Onaylandı"), (REJECTED, "Reddedildi"), (WITHDRAWN, "Geri alındı")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="leave_requests")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="leave_requests")
    requested_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, related_name="leave_requests")
    start_date = models.DateField("başlangıç")
    end_date = models.DateField("bitiş")
    periods = models.JSONField("saatler", default=list, blank=True)
    kind = models.CharField("tür", max_length=10, choices=KINDS, default="izin")
    reason = models.TextField("açıklama", blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField("yanıt", blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "izin bildirimi"
        verbose_name_plural = "izin bildirimleri"

    def __str__(self):
        return f"{self.teacher}: {self.start_date:%d.%m}–{self.end_date:%d.%m} {self.get_kind_display()}"

    @property
    def periods_label(self):
        return ", ".join(str(p + 1) for p in sorted(self.periods)) + ". saat" if self.periods else "tüm gün"

    def school_days(self):
        days, d = [], self.start_date
        while d <= self.end_date:
            if d.weekday() < self.school.days_per_week:
                days.append(d)
            d += datetime.timedelta(days=1)
        return days


class TeacherQuota(models.Model):
    """Öğretmen havuzu: bir ders adının kısımlarından bir öğretmenin kaç tanesini okutacağı (ör. TEM100:
    Ahmet 12, Mehmet 12, Ayşe 11). Üretimde kilitsiz kısımların öğretmenini çözücü bu kotalara göre seçer."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="teacher_quotas")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="teacher_quotas")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="quotas")
    count = models.PositiveSmallIntegerField("kısım sayısı")

    class Meta:
        verbose_name = "öğretmen kotası"
        verbose_name_plural = "öğretmen kotaları"
        constraints = [models.UniqueConstraint(fields=["subject", "teacher"], name="unique_teacher_quota")]


class AvailabilityRequest(models.Model):
    """Öğretmenin müsaitlik isteği ("şu saatlerde gelemem"). Program sorumlusu onaylayınca öğretmenin
    müsaitliğine yazılır. changes: [[gün, saat, durum], ...]; durum "no" gelemem, "maybe" tercih etmem,
    "" artık gelebilirim (kısıt kaldırılsın)."""

    PENDING = "bekliyor"
    APPROVED = "onaylandi"
    REJECTED = "reddedildi"
    WITHDRAWN = "geri_alindi"
    STATUS_CHOICES = [(PENDING, "Bekliyor"), (APPROVED, "Onaylandı"), (REJECTED, "Reddedildi"), (WITHDRAWN, "Geri alındı")]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="availability_requests")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="availability_requests")
    requested_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, related_name="availability_requests")
    changes = models.JSONField(default=list)
    reason = models.TextField("gerekçe", blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField("yanıt", blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "müsaitlik isteği"
        verbose_name_plural = "müsaitlik istekleri"

    def __str__(self):
        return f"{self.teacher}: {len(self.changes)} saat ({self.get_status_display()})"


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
    # İş kuyruğu (TIMETABLE_JOB_BACKEND="worker"): "queued" → "running"; çalışan süreç nabız yazar.
    job_state = models.CharField(max_length=10, blank=True, db_index=True)
    heartbeat = models.DateTimeField(null=True, blank=True)
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


class ImproveJob(models.Model):
    """Bütün okulu arka planda iyileştirme işi (school_improve.py). Sonuç programa uygulanmaz; öneri
    olarak saklanır ve çözüm merkezinde incelenip uygulanır."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [(QUEUED, "Sırada"), (RUNNING, "Çalışıyor"), (DONE, "Bitti"), (FAILED, "Başarısız"), (CANCELLED, "İptal edildi")]

    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE, related_name="improve_jobs")
    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=QUEUED)
    time_limit = models.PositiveIntegerField(default=1200, help_text="saniye")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat = models.DateTimeField(null=True, blank=True)
    stop_requested = models.BooleanField(default=False)
    progress = models.JSONField(default=dict, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "okul geneli iyileştirme"
        verbose_name_plural = "okul geneli iyileştirmeler"

    @property
    def active(self):
        return self.status in (self.QUEUED, self.RUNNING)


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
    # Gün yayılımı ve boşluk çeşitleri
    DAY_SPAN_MAX = "day_span_max"
    DAY_SPAN_MIN = "day_span_min"
    MIN_PER_DAY = "min_per_day"
    MIN_GAP_LENGTH = "min_gap_length"
    MIN_DISTANCE = "min_distance"
    GAPS_FROM_START = "gaps_from_start"
    GAPS_TO_END = "gaps_to_end"
    MAX_GAPS_WEEK = "max_gaps_week"
    GAPS_WEEK_FROM_START = "gaps_week_from_start"
    GAPS_WEEK_TO_END = "gaps_week_to_end"
    MAX_CONSEC_DAYS = "max_consec_days"
    MAX_FREE_DAYS = "max_free_days"
    # A/B sıralama
    AB_AFTER = "ab_after"
    AB_BEFORE = "ab_before"
    AB_NOT_MIXED = "ab_not_mixed"
    AB_WEEK_BEFORE = "ab_week_before"
    AB_DAY_BEFORE = "ab_day_before"
    AB_MAX_CONSECUTIVE = "ab_max_consecutive"
    AB_FILL_GAPS = "ab_fill_gaps"
    AB_A_FIRST = "ab_a_first"
    AB_B_AFTER = "ab_b_after"
    AB_NOT_FOLLOWED = "ab_not_followed"
    # Başlama ve bitiş
    ONLY_IN_MAP = "only_in_map"
    NO_START_AT = "no_start_at"
    NO_END_AT = "no_end_at"
    FIRST_OR_LAST = "first_or_last"
    RESERVE = "reserve"
    # Farklılık sayıları
    MAX_SUBJECTS_WEEK = "max_subjects_week"
    MAX_SUBJECTS_DAY = "max_subjects_day"
    MAX_TEACHERS_DAY = "max_teachers_day"
    MAX_ROOMS_DAY = "max_rooms_day"
    MAX_ROOM_CHANGES = "max_room_changes"
    MAX_BUILDING_CHANGES = "max_building_changes"
    MAX_BUILDINGS_WEEK = "max_buildings_week"
    MAX_ROOMS_POSITION = "max_rooms_position"
    # Seçmeli ve öğrenci kuralları (çözücüde değil, seçmeli dağıtımında uygulanır)
    ST_SAME_TEACHER = "st_same_teacher"
    ST_DIFF_TEACHER = "st_diff_teacher"
    ST_TEACHER_IN = "st_teacher_in"
    ST_TEACHER_NOT_IN = "st_teacher_not_in"
    ST_SAME_GROUP = "st_same_group"
    ST_TERM_BEFORE = "st_term_before"
    ST_TERM_BEFORE_SAME = "st_term_before_same"
    ST_SAME_TERM = "st_same_term"
    ST_DIFF_TERM = "st_diff_term"
    ST_MIN_ELECTIVES = "st_min_electives"
    ST_MAX_ELECTIVES = "st_max_electives"
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
        ("Gün yayılımı ve boşluklar (gelişmiş)", [
            (DAY_SPAN_MAX, "Günlük zaman harcaması (ilk dersten son derse, boşluklar dahil) en fazla N saat · aSc #19"),
            (DAY_SPAN_MIN, "Ders olan günlerde zaman harcaması en az N saat · aSc #18"),
            (MIN_PER_DAY, "Her gün en az N saat (boş gün olmaz) · aSc #29"),
            (MIN_GAP_LENGTH, "Boşluk varsa en az N saat sürsün · aSc #26"),
            (MIN_DISTANCE, "Gün içinde kartlar arasında en az N boş saat · aSc #75"),
            (GAPS_FROM_START, "Günlük boş saat en fazla N (1. saatten itibaren sayılır) · aSc #69"),
            (GAPS_TO_END, "Günlük boş saat en fazla N (son saate kadar sayılır) · aSc #70"),
            (MAX_GAPS_WEEK, "Haftalık boş saat en fazla N · aSc #5"),
            (GAPS_WEEK_FROM_START, "Haftalık boş saat en fazla N (ilk dersten önceki boşluklar dahil) · aSc #67"),
            (GAPS_WEEK_TO_END, "Haftalık boş saat en fazla N (son dersten sonraki boşluklar dahil) · aSc #68"),
            (MAX_CONSEC_DAYS, "Art arda en fazla N ders günü · aSc #23"),
            (MAX_FREE_DAYS, "Kartlar arasında en fazla N boş gün · aSc #20"),
        ]),
        ("A/B sıralama (gelişmiş)", [
            (AB_AFTER, "Aynı gün A dersleri B derslerinden sonra · aSc #30"),
            (AB_BEFORE, "Aynı gün A dersleri B derslerinden önce · aSc #40"),
            (AB_NOT_MIXED, "Aynı gün A dersleri B'den ya önce ya sonra (karışmaz) · aSc #34"),
            (AB_WEEK_BEFORE, "Hafta içinde tüm A dersleri B derslerinden önce · aSc #41"),
            (AB_DAY_BEFORE, "A'nın günleri B'nin günlerinden önce · aSc #42"),
            (AB_MAX_CONSECUTIVE, "A ve B birlikte art arda en fazla N saat · aSc #37"),
            (AB_FILL_GAPS, "A'nın gün içindeki boşlukları B dersleriyle dolsun · aSc #49"),
            (AB_A_FIRST, "B olan günde B'den önce en az bir A olsun · aSc #82"),
            (AB_B_AFTER, "A olan günde A'dan sonra en az bir B olsun · aSc #83"),
            (AB_NOT_FOLLOWED, "A'nın hemen ardından B gelmesin (sıralı) · aSc #22"),
        ]),
        ("Başlama ve bitiş", [
            (ONLY_IN_MAP, "Kartlar yalnızca işaretli saatlerde olsun · aSc #60"),
            (NO_START_AT, "İşaretli saatlerde ders başlamasın · aSc #32"),
            (NO_END_AT, "İşaretli saatlerde ders bitmesin · aSc #33"),
            (FIRST_OR_LAST, "Dersler ilk saatte başlasın ya da son saatte bitsin"),
            (RESERVE, "Rezerv alanı: işaretli saatler yalnızca seçilen derslere (sınıfın diğer dersleri giremez)"),
        ]),
        ("Farklılık sayıları (gelişmiş)", [
            (MAX_SUBJECTS_WEEK, "Haftada (işaretli saatlerde) en fazla N farklı ders · aSc #17"),
            (MAX_SUBJECTS_DAY, "Günde en fazla N farklı ders · aSc #54"),
            (MAX_TEACHERS_DAY, "Günde en fazla N farklı öğretmen · aSc #43"),
            (MAX_ROOMS_DAY, "Günde en fazla N farklı derslik · aSc #24"),
            (MAX_ROOM_CHANGES, "Günde en fazla N derslik değişimi · aSc #81"),
            (MAX_BUILDING_CHANGES, "Günde en fazla N bina değişimi · aSc #85"),
            (MAX_BUILDINGS_WEEK, "Haftada en fazla N farklı bina · aSc #79"),
            (MAX_ROOMS_POSITION, "Aynı saatte en fazla N derslik kullanılsın · aSc #39"),
        ]),
        ("Seçmeli ve öğrenci kuralları (seçmeli dağıtımında)", [
            (ST_SAME_TEACHER, "Öğrenci seçilen derslerde aynı öğretmene düşsün · aSc #35"),
            (ST_DIFF_TEACHER, "Öğrenci seçilen derslerde aynı öğretmene düşmesin · aSc #62"),
            (ST_TEACHER_IN, "Öğrenci bu derslerde seçili öğretmenlerden birine düşsün · aSc #65"),
            (ST_TEACHER_NOT_IN, "Öğrenci bu derslerde seçili öğretmenlere düşmesin · aSc #66"),
            (ST_SAME_GROUP, "Seçilen seçmelilerde aynı şubedeki öğrenciler birlikte kalsın · aSc #2"),
            (ST_TERM_BEFORE, "Öğrenci A seçmelisini B'den önceki dönemde alsın · aSc #44"),
            (ST_TERM_BEFORE_SAME, "Öğrenci A seçmelisini B'den önce ya da aynı dönemde alsın · aSc #45"),
            (ST_SAME_TERM, "Öğrenci A ve B seçmelilerini aynı dönemde alsın · aSc #46"),
            (ST_DIFF_TERM, "Öğrenci A ve B seçmelilerini aynı dönemde almasın · aSc #47"),
            (ST_MIN_ELECTIVES, "Seçilen derslerden en az N seçmeli · aSc #52"),
            (ST_MAX_ELECTIVES, "Seçilen derslerden en fazla N seçmeli · aSc #53"),
        ]),
    ]
    # Seçilen derslerin i. kartlarını eşleştiren koşullar (her ders bir küme).
    PAIRED = {SAME_TIME, SAME_DAY, CONSECUTIVE, CONSECUTIVE_ORDERED}
    TWO_SIDED = {
        AB_NOT_SAME_DAY, AB_NOT_CONSECUTIVE, AB_NOT_DAY_AFTER, AB_AFTER, AB_BEFORE, AB_NOT_MIXED, AB_WEEK_BEFORE,
        AB_DAY_BEFORE, AB_MAX_CONSECUTIVE, AB_FILL_GAPS, AB_A_FIRST, AB_B_AFTER, AB_NOT_FOLLOWED,
        ST_TERM_BEFORE, ST_TERM_BEFORE_SAME, ST_SAME_TERM, ST_DIFF_TERM,
    }
    ROOMS = {ROOM_MAX_WEEK, ROOM_MIN_WEEK}
    # Çözücüye gitmeyen, seçmeli dağıtımında uygulanan kurallar.
    STUDENT = {
        ST_SAME_TEACHER, ST_DIFF_TEACHER, ST_TEACHER_IN, ST_TEACHER_NOT_IN, ST_SAME_GROUP, ST_TERM_BEFORE,
        ST_TERM_BEFORE_SAME, ST_SAME_TERM, ST_DIFF_TERM, ST_MIN_ELECTIVES, ST_MAX_ELECTIVES,
    }
    # Öğretmen alanı süzgeç değil, kuralın öğretmen listesi olan koşullar.
    TEACHER_LIST = {ST_TEACHER_IN, ST_TEACHER_NOT_IN}
    USES_N = {
        MAX_PER_DAY, MIN_GAP_DAYS, MAX_DAYS, MIN_DAYS, RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK,
        MAP_MIN_WEEK, MAP_MIN_IF_ANY, MAX_CONSECUTIVE, MAX_GAPS_PER_DAY, MAX_GAP_LENGTH, MAX_DISTINCT_PERIODS,
        MAX_SAME_PERIOD_DAYS, MAX_PER_POSITION, MIN_PER_POSITION, ROOM_MAX_WEEK, ROOM_MIN_WEEK, MAX_ROOMS_WEEK,
        MAX_BUILDINGS_DAY, DAY_SPAN_MAX, DAY_SPAN_MIN, MIN_PER_DAY, MIN_GAP_LENGTH, MIN_DISTANCE, GAPS_FROM_START,
        GAPS_TO_END, MAX_GAPS_WEEK, GAPS_WEEK_FROM_START, GAPS_WEEK_TO_END, MAX_CONSEC_DAYS, MAX_FREE_DAYS,
        AB_MAX_CONSECUTIVE, MAX_SUBJECTS_WEEK, MAX_SUBJECTS_DAY, MAX_TEACHERS_DAY, MAX_ROOMS_DAY, MAX_ROOM_CHANGES,
        MAX_BUILDING_CHANGES, MAX_BUILDINGS_WEEK, MAX_ROOMS_POSITION, ST_MIN_ELECTIVES, ST_MAX_ELECTIVES,
    }
    # "En fazla N" koşulları: istisna üst sınırı (param_max) verilebilir.
    SOFT_TARGET = {
        MAX_PER_DAY, MAX_DAYS, RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK, MAX_CONSECUTIVE, MAX_GAPS_PER_DAY,
        MAX_GAP_LENGTH, MAX_DISTINCT_PERIODS, MAX_SAME_PERIOD_DAYS, MAX_PER_POSITION, ROOM_MAX_WEEK, MAX_ROOMS_WEEK,
        MAX_BUILDINGS_DAY, DAY_SPAN_MAX, GAPS_FROM_START, GAPS_TO_END, MAX_GAPS_WEEK, GAPS_WEEK_FROM_START,
        GAPS_WEEK_TO_END, MAX_CONSEC_DAYS, MAX_FREE_DAYS, AB_MAX_CONSECUTIVE, MAX_SUBJECTS_WEEK, MAX_SUBJECTS_DAY,
        MAX_TEACHERS_DAY, MAX_ROOMS_DAY, MAX_ROOM_CHANGES, MAX_BUILDING_CHANGES, MAX_BUILDINGS_WEEK, MAX_ROOMS_POSITION,
    }
    # Zaman haritasını kullanan koşullar (harita boşsa tüm hücreler sayılır).
    USES_MAP = {
        MAX_DAYS, RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK, MAP_MIN_WEEK, MAP_MIN_IF_ANY, MAX_PER_POSITION,
        MIN_PER_POSITION, AB_NOT_SAME_DAY, AB_NOT_DAY_AFTER, ROOM_MAX_WEEK, ROOM_MIN_WEEK, MIN_PER_DAY,
        NO_START_AT, NO_END_AT, RESERVE, MAX_SUBJECTS_WEEK, ONLY_IN_MAP,
    }
    NEEDS_MAP = {
        RANGE_MAX_PER_DAY, RANGE_MAX_DAYS, MAP_MAX_WEEK, MAP_MIN_WEEK, MAP_MIN_IF_ANY, MIN_PER_POSITION, NO_START_AT,
        NO_END_AT, RESERVE, ONLY_IN_MAP,
    }

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
    param_max = models.PositiveSmallIntegerField(
        "istisna üst sınırı", null=True, blank=True,
        help_text="Doluysa N tercih edilen sınır olur (aşılması cezalandırılır), bu değer ise hiç aşılamaz. "
                  "Ör. öğretmen günde en fazla 6 saat, zorunlu kalırsa 8.",
    )
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
    note = models.CharField("not", max_length=300, blank=True)

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
    periods = models.JSONField("saatler", default=list, blank=True, help_text="Boş = tüm gün; ör. [2, 3] yalnızca 3. ve 4. saat")

    def covers(self, period):
        return not self.periods or period in self.periods

    @property
    def periods_label(self):
        return ", ".join(str(p + 1) for p in sorted(self.periods)) + ". saat" if self.periods else "tüm gün"

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


class LessonRef(models.Model):
    """ÜYBS referansı: bir dersin bir sınıftaki (kısımdaki) kaçıncı haftalık saatine ait kimlik.

    Referans saatin sırasına bağlıdır, gün/saate değil: ders Pazartesi 1–2'den Salı 3–4'e taşınsa da
    1. saat 1001, 2. saat 1002 olarak kalır. Sıra, programdaki yerleşime göre (gün, saat) belirlenir.
    """

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="refs")
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE, null=True, blank=True, related_name="lesson_refs")
    ordinal = models.PositiveSmallIntegerField("saat sırası")
    ref = models.CharField("ÜYBS ref", max_length=50)

    class Meta:
        ordering = ["lesson", "school_class", "ordinal"]
        verbose_name = "ÜYBS referansı"
        verbose_name_plural = "ÜYBS referansları"
        constraints = [models.UniqueConstraint(fields=["lesson", "school_class", "ordinal"], name="unique_lesson_ref")]

    def __str__(self):
        return f"{self.lesson} #{self.ordinal} = {self.ref}"


class AuditLog(models.Model):
    """İşlem günlüğü: kim, ne zaman, hangi kurum/programda ne yaptı."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    username = models.CharField(max_length=150, blank=True)
    institution = models.ForeignKey(Institution, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    school = models.ForeignKey(School, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    program_name = models.CharField(max_length=200, blank=True)
    action = models.CharField("işlem", max_length=100)
    detail = models.TextField("ayrıntı", blank=True)
    path = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "işlem kaydı"
        verbose_name_plural = "işlem günlüğü"

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.username}: {self.action}"


class WeekArchive(models.Model):
    """ÜYBS aktarımının bir haftalık arşivi: o haftanın satırları alındığı haliyle saklanır.

    Program sonradan değişse de geçmiş haftanın raporu o haftanın gerçek yerleşimiyle çıkar."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="week_archives")
    week_start = models.DateField("hafta (pazartesi)")
    source = models.CharField("kaynak sürüm", max_length=200, blank=True)
    rows = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-week_start"]
        verbose_name = "hafta arşivi"
        verbose_name_plural = "hafta arşivleri"
        constraints = [models.UniqueConstraint(fields=["school", "week_start"], name="unique_week_archive")]

    def __str__(self):
        return f"{self.school} {self.week_start:%d.%m.%Y}"


class Student(models.Model):
    """Öğrenci: sınıfı, bölünmelerdeki grupları ve seçtiği seçmeli dersler."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="students")
    number = models.CharField("numara", max_length=30, blank=True)
    first_name = models.CharField("ad", max_length=100)
    last_name = models.CharField("soyad", max_length=100, blank=True)
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name="students", verbose_name="sınıf"
    )
    groups = models.ManyToManyField(Group, blank=True, related_name="students", verbose_name="gruplar")
    choices = models.ManyToManyField(Subject, blank=True, related_name="choosers", verbose_name="seçtiği dersler")

    class Meta:
        ordering = ["school_class__sort_key", "number", "last_name", "first_name"]
        verbose_name = "öğrenci"
        verbose_name_plural = "öğrenciler"

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
