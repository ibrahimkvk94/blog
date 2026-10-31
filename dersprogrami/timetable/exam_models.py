"""Sınav programı (vize / final / bütünleme) veri modeli.

- ExamPeriod (sınav dönemi): tarih aralığı, hariç günler, günlük oturum saatleri ve kurallar.
- Exam (sınav): bir ders adının bir ya da birden çok sınıfa ortak sınavı; derslerden üretilir, elle düzenlenir.
- ExamPlacement: sınavın yerleştiği gün + oturum; ExamRoom: kullandığı salonlar, oturan öğrenci ve gözetmenler.

Modeller models.py'nin sonunda içe aktarılır (uygulama etiketi "timetable").
"""

import datetime

from django.db import models

DEFAULT_SESSIONS = ["09:30", "11:00", "13:30", "15:00"]


class ExamPeriod(models.Model):
    VIZE, FINAL, BUT, OTHER = "vize", "final", "butunleme", "diger"
    KIND_CHOICES = [(VIZE, "Vize (ara sınav)"), (FINAL, "Final (yarıyıl sonu)"), (BUT, "Bütünleme"), (OTHER, "Diğer")]

    IDLE, RUNNING, OK, PARTIAL, FAILED = "", "running", "ok", "partial", "failed"
    STATUS_CHOICES = [(IDLE, "Oluşturulmadı"), (RUNNING, "Oluşturuluyor"), (OK, "Oluşturuldu"),
                      (PARTIAL, "Kısmen oluşturuldu"), (FAILED, "Oluşturulamadı")]

    school = models.ForeignKey("timetable.School", on_delete=models.CASCADE, related_name="exam_periods")
    name = models.CharField("ad", max_length=200, help_text="Ör. 2026 Güz Vize")
    kind = models.CharField("tür", max_length=12, choices=KIND_CHOICES, default=VIZE)
    start_date = models.DateField("başlangıç")
    end_date = models.DateField("bitiş")
    weekdays = models.JSONField("sınav günleri", default=list, blank=True, help_text="0 = Pazartesi; boş = Pazartesi–Cuma")
    excluded_dates = models.JSONField("hariç günler", default=list, blank=True, help_text='"YYYY-AA-GG" listesi (tatil vb.)')
    sessions = models.JSONField("oturum saatleri", default=list, blank=True, help_text='Ör. ["09:30", "11:00", "13:30", "15:00"]')
    exam_minutes = models.PositiveSmallIntegerField(
        "oturum süresi (dk)", default=60, help_text="Gözetmen müsaitliği bu süreye göre ders saatleriyle eşlenir.")
    max_per_day = models.PositiveSmallIntegerField("sınıfın günde en fazla sınavı", default=2)
    proctors_per_room = models.PositiveSmallIntegerField("salon başına gözetmen", default=1)
    capacity_percent = models.PositiveSmallIntegerField(
        "sınav kapasitesi (%)", default=50, help_text="Salonun sınavda alacağı öğrenci = derslik kapasitesi × bu oran.")
    default_seats = models.PositiveSmallIntegerField(
        "kapasitesiz derslikte sınav kapasitesi", null=True, blank=True,
        help_text="Kapasitesi girilmemiş derslikler bu kadar öğrenciyle sınav salonu sayılır; boş = kullanılmaz.")
    use_availability = models.BooleanField(
        "öğretmen müsaitliğini kullan", default=True,
        help_text="Öğretmenin ders programındaki yasak saatleri (aynı hafta günü ve saatte) gözetmenlikte de kapalı sayılır.")
    rooms = models.ManyToManyField("timetable.Classroom", blank=True, related_name="+", verbose_name="sınav salonları",
                                   help_text="Boş = sınav kapasitesi olan tüm derslikler.")
    proctor_exempt = models.ManyToManyField("timetable.Teacher", blank=True, related_name="+", verbose_name="gözetmenlikten muaf")
    # Öğretmenin gözetmenlik yapamayacağı gün/oturumlar: {"öğretmen kimliği": ["2026-11-02", "2026-11-03#1", ...]}
    # ("#n" yalnızca o günün n. oturumu, 0'dan başlar).
    proctor_blocks = models.JSONField(default=dict, blank=True)
    time_limit = models.PositiveSmallIntegerField("süre sınırı (sn)", default=30)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=IDLE, blank=True)
    report = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        verbose_name = "sınav dönemi"
        verbose_name_plural = "sınav dönemleri"

    def __str__(self):
        return self.name

    @property
    def session_times(self):
        return list(self.sessions or DEFAULT_SESSIONS)

    @property
    def active_weekdays(self):
        return sorted(set(self.weekdays)) if self.weekdays else [0, 1, 2, 3, 4]

    def dates(self):
        """Sınav yapılabilecek günler (hafta günü uygun, hariç tutulmamış)."""
        excluded = set(self.excluded_dates or [])
        days, d = [], self.start_date
        allowed = set(self.active_weekdays)
        while d <= self.end_date and len(days) < 400:
            if d.weekday() in allowed and d.isoformat() not in excluded:
                days.append(d)
            d += datetime.timedelta(days=1)
        return days

    def slots(self):
        """[(tarih, oturum sırası), ...] zaman sırasıyla."""
        n = len(self.session_times)
        return [(d, s) for d in self.dates() for s in range(n)]

    @property
    def is_running(self):
        return self.status == self.RUNNING


class Exam(models.Model):
    period = models.ForeignKey(ExamPeriod, on_delete=models.CASCADE, related_name="exams")
    subject = models.ForeignKey("timetable.Subject", on_delete=models.CASCADE, related_name="exams", verbose_name="ders adı")
    name = models.CharField("ad", max_length=200, blank=True, help_text="Boş = ders adı")
    classes = models.ManyToManyField("timetable.SchoolClass", blank=True, related_name="exams", verbose_name="sınıflar")
    lessons = models.ManyToManyField("timetable.Lesson", blank=True, related_name="exams", verbose_name="kaynak dersler")
    teachers = models.ManyToManyField("timetable.Teacher", blank=True, related_name="exams", verbose_name="dersin öğretmenleri")
    duration = models.PositiveSmallIntegerField("süre (oturum)", default=1)
    student_count = models.PositiveIntegerField("öğrenci sayısı", default=0)
    count_manual = models.BooleanField("öğrenci sayısı elle girildi", default=False)
    fixed_date = models.DateField("sabit tarih", null=True, blank=True)
    fixed_session = models.PositiveSmallIntegerField("sabit oturum", null=True, blank=True, help_text="0'dan başlar")
    rooms_needed = models.PositiveSmallIntegerField("gereken salon sayısı", null=True, blank=True, help_text="Boş = kapasiteye göre")
    allowed_rooms = models.ManyToManyField("timetable.Classroom", blank=True, related_name="+", verbose_name="yalnızca bu salonlar")
    excluded = models.BooleanField("sınav yapılmaz", default=False)
    note = models.CharField("not", max_length=200, blank=True)

    class Meta:
        ordering = ["subject__name", "id"]
        verbose_name = "sınav"
        verbose_name_plural = "sınavlar"

    def __str__(self):
        return self.title

    @property
    def title(self):
        return self.name or self.subject.name


class ExamPlacement(models.Model):
    exam = models.OneToOneField(Exam, on_delete=models.CASCADE, related_name="placement")
    date = models.DateField("tarih")
    session = models.PositiveSmallIntegerField("oturum", help_text="0'dan başlar")
    locked = models.BooleanField("kilitli", default=False, help_text="Yeniden oluşturmada yeri ve salonları korunur.")

    class Meta:
        ordering = ["date", "session"]
        verbose_name = "sınav yerleşimi"
        verbose_name_plural = "sınav yerleşimleri"

    def __str__(self):
        return f"{self.exam} @ {self.date:%d.%m.%Y} {self.session + 1}. oturum"


class ExamRoom(models.Model):
    placement = models.ForeignKey(ExamPlacement, on_delete=models.CASCADE, related_name="rooms")
    classroom = models.ForeignKey("timetable.Classroom", on_delete=models.CASCADE, related_name="+", verbose_name="salon")
    seats = models.PositiveIntegerField("öğrenci", default=0)
    proctors = models.ManyToManyField("timetable.Teacher", blank=True, related_name="proctorings", verbose_name="gözetmenler")

    class Meta:
        ordering = ["classroom__name"]
        verbose_name = "sınav salonu"
        verbose_name_plural = "sınav salonları"
