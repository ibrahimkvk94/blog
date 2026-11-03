"""Sınav programı (vize / final / bütünleme) veri modeli.

- ExamPeriod (sınav dönemi): tarih aralığı, hariç günler, günlük oturum saatleri ve kurallar.
- Exam (sınav): bir ders adının bir ya da birden çok sınıfa ortak sınavı; derslerden üretilir, elle düzenlenir.
- ExamPlacement: sınavın yerleştiği gün + oturum; ExamRoom: kullandığı salonlar, oturan öğrenci ve gözetmenler.

Modeller önceden "timetable" uygulamasındaydı; tablolar aynı adla kaldı (db_table), veri taşınmadı.
Ders Planlama'nın ortak verisine (program, ders adı, sınıf, ders, öğretmen, derslik) bağlıdır.
"""

import datetime

from django.conf import settings
from django.db import models

DEFAULT_SESSIONS = ["09:30", "11:00", "13:30", "15:00"]

# Görev rolleri (KAMYOSİS, PPYS SPS kuralı): salon amiri, gözetmen, taşıyıcı. Rolsüz dönemde herkes gözetmendir.
AMIR, GOZETMEN, TASIYICI = "A", "G", "T"
ROLE_NAMES = {AMIR: "Salon amiri", GOZETMEN: "Gözetmen", TASIYICI: "Taşıyıcı"}
ROLE_ORDER = (AMIR, GOZETMEN, TASIYICI)
DEFAULT_ROLES = GOZETMEN + TASIYICI  # rolleri girilmemiş öğretmen: gözetmen ve taşıyıcı olabilir, salon amiri olamaz


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
    # KAMYOSİS: "mümkünse görev verilmesin" oturumları (biçim proctor_blocks ile aynı); çözücü yalnızca gerekirse kullanır
    proctor_soft = models.JSONField(default=dict, blank=True)
    duty_roles = models.BooleanField(
        "görev rolleri", default=False,
        help_text="Açıksa salon başına: 40 ve üstü öğrencide 1 salon amiri; 40'tan az öğrencide 1, fazlasında her 20 "
                  "öğrenciye 1 gözetmen; öğrencisi olan salona 1 taşıyıcı. Kapalıysa salon başına sabit gözetmen sayısı.")
    # KAMYOSİS: öğretmenin alabileceği roller {"öğretmen kimliği": "AGT"}; kayıt yok = DEFAULT_ROLES, "" = görev almaz
    proctor_roles = models.JSONField(default=dict, blank=True)
    time_limit = models.PositiveSmallIntegerField("süre sınırı (sn)", default=30)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=IDLE, blank=True)
    report = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        db_table = "timetable_examperiod"
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

    def roles_of(self, teacher_id):
        """Öğretmenin bu dönemde alabileceği roller ("AGT" alt kümesi). Rolsüz dönemde gözetmen olabilen herkes."""
        roles = (self.proctor_roles or {}).get(str(teacher_id), DEFAULT_ROLES)
        if not self.duty_roles:
            return GOZETMEN if roles else ""
        return "".join(r for r in ROLE_ORDER if r in roles)


class Exam(models.Model):
    period = models.ForeignKey(ExamPeriod, on_delete=models.CASCADE, related_name="exams")
    subject = models.ForeignKey("timetable.Subject", on_delete=models.CASCADE, related_name="exams", verbose_name="ders adı")
    # KAMYOSİS: sınavlar ders koduna göre oluşur; tür ve zorluk ExamCourse'tan bu kodla okunur (bkz. kurallar.py)
    code = models.CharField("ders kodu", max_length=60, blank=True, db_index=True)
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
        db_table = "timetable_exam"
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
        db_table = "timetable_examplacement"
        verbose_name = "sınav yerleşimi"
        verbose_name_plural = "sınav yerleşimleri"

    def __str__(self):
        return f"{self.exam} @ {self.date:%d.%m.%Y} {self.session + 1}. oturum"


class ExamRoom(models.Model):
    placement = models.ForeignKey(ExamPlacement, on_delete=models.CASCADE, related_name="rooms")
    classroom = models.ForeignKey("timetable.Classroom", on_delete=models.CASCADE, related_name="+", verbose_name="salon")
    seats = models.PositiveIntegerField("öğrenci", default=0)
    proctors = models.ManyToManyField("timetable.Teacher", blank=True, related_name="proctorings", verbose_name="gözetmenler")
    # KAMYOSİS: görevlinin rolü {"öğretmen kimliği": "A" | "T"}; kayıt yok = gözetmen
    roles = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["classroom__name"]
        db_table = "timetable_examroom"
        verbose_name = "sınav salonu"
        verbose_name_plural = "sınav salonları"

    def role_of(self, teacher_id):
        return (self.roles or {}).get(str(teacher_id), GOZETMEN)

    @property
    def duties(self):
        """[(öğretmen, rol kodu, rol adı)] salon amiri, gözetmen, taşıyıcı sırasıyla (proctors önceden yüklenmiş olmalı)."""
        rows = [(t, self.role_of(t.pk)) for t in self.proctors.all()]
        rows.sort(key=lambda r: (ROLE_ORDER.index(r[1]) if r[1] in ROLE_ORDER else 9, r[0].last_name, r[0].first_name))
        return [(t, r, ROLE_NAMES.get(r, r)) for t, r in rows]


class ExamCourse(models.Model):
    """KAMYOSİS: dersin (ders kodu) sınav bilgisi — sınav türü ve zorluk. Kurum düzeyindedir; her dönem yeniden
    girilmez. Excel'den aktarılır, "Ders sınav bilgileri" sayfasından düzenlenir (bkz. kurallar.py)."""

    institution = models.ForeignKey("timetable.Institution", on_delete=models.CASCADE, related_name="exam_courses")
    code = models.CharField("ders kodu", max_length=60)
    exam_type = models.CharField("sınav türü", max_length=80, blank=True, help_text="Ör. %100 MT, %40 MT + %60 UYG, %100 UYG")
    difficulty = models.PositiveSmallIntegerField("zorluk", default=3, help_text="1–5; 5 olanlar mümkün olduğunca önce yerleşir")

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["institution", "code"], name="sinav_examcourse_tekil")]
        verbose_name = "ders sınav bilgisi"
        verbose_name_plural = "ders sınav bilgileri"

    def __str__(self):
        return f"{self.code} {self.exam_type}".strip()


class ExamDutyChange(models.Model):
    """KAMYOSİS: program oluştuktan sonra elle yapılan görev değişikliği (başka öğretmene verme ya da takas) kaydı."""

    REPLACE, SWAP = "replace", "swap"
    KIND_CHOICES = [(REPLACE, "Başka öğretmene verildi"), (SWAP, "Takas")]

    period = models.ForeignKey(ExamPeriod, on_delete=models.CASCADE, related_name="duty_changes")
    kind = models.CharField("işlem", max_length=10, choices=KIND_CHOICES)
    summary = models.TextField("değişiklik")
    reason = models.CharField("gerekçe", max_length=200)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "görev değişikliği"
        verbose_name_plural = "görev değişiklikleri"

    def __str__(self):
        return self.summary
