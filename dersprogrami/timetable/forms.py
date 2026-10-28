"""Veri giriş formları. Tüm seçim alanları ilgili okulun kayıtlarıyla sınırlanır."""

import json

from django import forms
from django.core.exceptions import ValidationError

from .models import (
    DAY_NAMES,
    Building,
    CardRelationship,
    Classroom,
    Group,
    Lesson,
    Period,
    School,
    SchoolClass,
    Subject,
    Teacher,
)


class ChipSelectMultiple(forms.CheckboxSelectMultiple):
    """Seçenekleri arama kutulu "çip" listesi olarak gösterir."""

    template_name = "timetable/data/widgets/chips.html"

    def __init__(self, *args, searchable=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.searchable = searchable

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["searchable"] = self.searchable
        return context

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if isinstance(instance, Group):
            option["group_class"] = instance.division.school_class_id
        return option


class StyledFormMixin:
    """Alanlara tasarım sistemindeki sınıfları ekler."""

    def _style(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxSelectMultiple, forms.CheckboxInput, forms.RadioSelect)):
                continue
            css = "select" if isinstance(widget, forms.Select) else "input"
            widget.attrs.setdefault("class", css)


class SchoolForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "days_per_week", "weeks_count", "terms_count", "linked_programs"]
        widgets = {"days_per_week": forms.Select(choices=[(n, f"{n} gün ({', '.join(DAY_NAMES[:n])})") for n in range(1, 8)])}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["weeks_count"].widget = forms.Select(choices=[(1, "Her hafta aynı"), (2, "İki haftalık (A/B)")])
        self.fields["terms_count"].widget = forms.Select(choices=[(1, "Tek dönem"), (2, "İki dönem")])
        others = School.objects.none()
        if self.instance.pk and self.instance.institution_id:
            others = School.objects.filter(institution_id=self.instance.institution_id).exclude(pk=self.instance.pk)
        if others.exists():
            self.fields["linked_programs"].queryset = others
            self.fields["linked_programs"].widget = ChipSelectMultiple(searchable=False)
            self.fields["linked_programs"].widget.choices = self.fields["linked_programs"].choices
        else:
            del self.fields["linked_programs"]
        self._style()


class PeriodForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Period
        fields = ["name", "start_time", "end_time", "long_break_after"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False  # boş bırakılırsa "N. saat" verilir
        self._style()

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end <= start:
            raise ValidationError("Bitiş saati başlangıçtan sonra olmalı.")
        return data


PeriodFormSet = forms.modelformset_factory(Period, form=PeriodForm, extra=0, can_delete=True)


class SchoolScopedForm(StyledFormMixin, forms.ModelForm):
    """school alanını formdan gizler ve seçimleri okulla sınırlar."""

    scoped = {}  # alan adı -> (model, okul ilişkisi yolu)

    def __init__(self, *args, school, **kwargs):
        self.school = school
        super().__init__(*args, **kwargs)
        for name, (model, path) in self.scoped.items():
            if name in self.fields:
                self.fields[name].queryset = model.objects.filter(**{path: school})
        self._style()

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.school = self.school
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class SubjectForm(SchoolScopedForm):
    scoped = {"classrooms": (Classroom, "school")}

    class Meta:
        model = Subject
        fields = ["name", "short", "color", "classrooms"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"}), "classrooms": ChipSelectMultiple()}


class BuildingForm(SchoolScopedForm):
    class Meta:
        model = Building
        fields = ["name"]


class TeacherForm(SchoolScopedForm):
    scoped = {"subjects": (Subject, "school"), "home_classroom": (Classroom, "school")}

    class Meta:
        model = Teacher
        fields = [
            "first_name", "last_name", "short", "department", "title", "target_periods", "home_classroom",
            "max_periods_per_day", "min_periods_per_day", "max_consecutive",
            "max_gaps_per_day", "max_gaps_per_week", "max_days_per_week", "duty_exempt", "max_duties", "subjects",
            "tc_no", "email",
        ]
        widgets = {"subjects": ChipSelectMultiple()}
        help_texts = {
            "max_periods_per_day": "Boş = sınır yok",
            "max_gaps_per_day": "Boş = sınır yok",
            "max_gaps_per_week": "Boş = sınır yok",
            "max_days_per_week": "Ör. 4 = haftada bir boş gün",
        }

    def clean_tc_no(self):
        tc = (self.cleaned_data.get("tc_no") or "").strip()
        if tc and not (tc.isdigit() and len(tc) == 11):
            raise forms.ValidationError("TC kimlik no 11 haneli olmalı.")
        return tc


class ClassroomForm(SchoolScopedForm):
    scoped = {"building": (Building, "school")}

    class Meta:
        model = Classroom
        fields = ["name", "short", "capacity", "max_lessons", "building"]


class SchoolClassForm(SchoolScopedForm):
    scoped = {"home_classroom": (Classroom, "school"), "class_teacher": (Teacher, "school")}

    class Meta:
        model = SchoolClass
        fields = ["name", "short", "grade", "class_teacher", "home_classroom", "student_count", "min_periods_per_day", "max_periods_per_day", "uybs_no"]
        help_texts = {"home_classroom": "Derslik seçilmemiş tek sınıflık dersler bu derslikte yapılır."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_teacher"].label_from_instance = lambda t: t.full_name


class LessonForm(SchoolScopedForm):
    scoped = {
        "subject": (Subject, "school"),
        "classes": (SchoolClass, "school"),
        "groups": (Group, "division__school_class__school"),
        "teachers": (Teacher, "school"),
        "classrooms": (Classroom, "school"),
    }

    class Meta:
        model = Lesson
        fields = [
            "subject", "classes", "groups", "teachers", "classrooms", "periods_per_week", "card_length", "split",
            "max_per_day", "rooms_needed", "weeks_mask", "terms_mask", "elective", "capacity",
        ]
        widgets = {
            "classes": ChipSelectMultiple(),
            "groups": ChipSelectMultiple(searchable=False),
            "teachers": ChipSelectMultiple(),
            "classrooms": ChipSelectMultiple(),
            "card_length": forms.Select(choices=[(1, "Tekil (1 saat)"), (2, "Blok (2 saat)"), (3, "3 saatlik blok"), (4, "4 saatlik blok")]),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].label_from_instance = lambda s: s.name
        self.fields["groups"].queryset = self.fields["groups"].queryset.select_related("division__school_class")
        self.fields["groups"].label_from_instance = lambda g: f"{g.division.school_class} · {g.name}"
        self.fields["teachers"].label_from_instance = lambda t: f"{t.first_name} {t.last_name}"
        self.fields["split"].widget.attrs["placeholder"] = "ör. 2+2+1"
        self.fields["rooms_needed"].required = False
        weeks, terms = self.school.weeks_count, self.school.terms_count
        if weeks > 1:
            self.fields["weeks_mask"] = forms.TypedChoiceField(
                label="Haftalar", choices=[("", "Her hafta"), (1, "Yalnızca A haftası"), (2, "Yalnızca B haftası")],
                coerce=int, empty_value=None, required=False, widget=forms.Select(attrs={"class": "select"}),
            )
        else:
            del self.fields["weeks_mask"]
        if terms > 1:
            self.fields["terms_mask"] = forms.TypedChoiceField(
                label="Dönem", choices=[("", "Tüm yıl"), (1, "1. dönem"), (2, "2. dönem")],
                coerce=int, empty_value=None, required=False, widget=forms.Select(attrs={"class": "select"}),
            )
        else:
            del self.fields["terms_mask"]

    def clean(self):
        data = super().clean()
        classes = set(data.get("classes") or [])
        for group in data.get("groups") or []:
            if group.division.school_class not in classes:
                self.add_error("groups", f"“{group}” grubu seçilen sınıflardan birine ait değil.")
        if not classes and not data.get("teachers"):
            self.add_error("classes", "En az bir sınıf ya da (toplantı gibi sınıfsız dersler için) bir öğretmen seçin.")
        periods = self.school.periods.count()
        if data.get("card_length") and periods and data["card_length"] > periods:
            self.add_error("card_length", f"Kart uzunluğu günlük ders saatinden ({periods}) uzun olamaz.")
        split = (data.get("split") or "").strip()
        if split:
            parts = Lesson.parse_split(split)
            if not parts:
                self.add_error("split", "Dağılımı “2+2+1” biçiminde yazın.")
            elif data.get("periods_per_week") and sum(parts) != data["periods_per_week"]:
                self.add_error("split", f"Dağılımın toplamı ({sum(parts)}) haftalık saate ({data['periods_per_week']}) eşit olmalı.")
            elif periods and max(parts) > periods:
                self.add_error("split", f"Bir kart günlük ders saatinden ({periods}) uzun olamaz.")
            else:
                data["split"] = "+".join(str(p) for p in parts)
        if not data.get("rooms_needed"):
            data["rooms_needed"] = 1
        if data.get("periods_per_week") == 0:
            self.add_error("periods_per_week", "Haftalık saat en az 1 olmalı.")
        return data


class RelationshipForm(SchoolScopedForm):
    scoped = {
        "lessons": (Lesson, "school"),
        "subjects": (Subject, "school"),
        "lessons_b": (Lesson, "school"),
        "subjects_b": (Subject, "school"),
        "classes": (SchoolClass, "school"),
        "teachers": (Teacher, "school"),
        "classrooms": (Classroom, "school"),
    }

    class Meta:
        model = CardRelationship
        fields = [
            "name", "active", "condition", "param", "param_max", "apply_to", "importance", "card_length",
            "subjects", "lessons", "subjects_b", "lessons_b", "classes", "teachers", "classrooms",
            "time_map", "time_map_b",
        ]
        widgets = {
            "subjects": ChipSelectMultiple(),
            "lessons": ChipSelectMultiple(),
            "subjects_b": ChipSelectMultiple(),
            "lessons_b": ChipSelectMultiple(),
            "classes": ChipSelectMultiple(),
            "teachers": ChipSelectMultiple(),
            "classrooms": ChipSelectMultiple(),
            "time_map": forms.HiddenInput(),
            "time_map_b": forms.HiddenInput(),
        }
        labels = {"subjects": "A tarafı / küme: ders adları", "lessons": "A tarafı / küme: dersler"}
        help_texts = {
            "param": "Koşuldaki N sayısı.",
            "importance": "Kesin kurallar mutlaka sağlanır; diğerleri ihlal edilirse ceza puanı eklenir.",
            "card_length": "Boş = tüm kartlar. Ör. “blok ders Pazartesi olmasın” için 2 saatlik blokları seçin.",
        }

    CONDITION_HELP = {
        CardRelationship.MAX_PER_DAY: "Her kümede bir günde en fazla N kart olur. Ör. her sınıfta sayısal derslerden günde en fazla 2.",
        CardRelationship.DIFFERENT_DAYS: "Kümedeki kartların hepsi farklı günlere düşer. Ör. Fizik ve Kimya aynı gün olmasın.",
        CardRelationship.MIN_GAP_DAYS: "Kümedeki iki kart arasında en az N boş gün olur. Ör. N=1: Pazartesi ve Çarşamba olur, Salı olmaz.",
        CardRelationship.MAX_DAYS: "Kümedeki kartlar en fazla N farklı güne yayılır. Haritada günler işaretlenirse yalnızca o günler sayılır: ör. Coğrafya Pazartesi ve Cuma'dan en fazla birinde.",
        CardRelationship.MIN_DAYS: "Kümedeki kartlar haftada en az N farklı güne yayılır.",
        CardRelationship.RANGE_MAX_PER_DAY: "İşaretli saatlerde her gün en fazla N saat ders olur. Ör. öğle arası için 4–6. saatlerde en fazla 2; N=0 ile işaretli saatler bu dersler için kapanır.",
        CardRelationship.RANGE_MAX_DAYS: "İşaretli saatlerde dersi olan en fazla N gün olur. Ör. öğleden sonraları haftada en fazla 2 gün (her öğretmen için ayrı).",
        CardRelationship.MAP_MAX_WEEK: "İşaretli saatlerde haftada en fazla N saat ders olur. Ör. her sınıfta Tarih 6–7. saatlerde haftada en fazla 1.",
        CardRelationship.MAP_MIN_WEEK: "İşaretli saatlerde haftada en az N saat ders olur. Ör. Biyoloji'nin en az 2 saati 4. saatten önce; her öğretmen 1–3. saatlerde en az bir ders.",
        CardRelationship.MAP_MIN_IF_ANY: "O gün işaretli saatlerde ders varsa en az N saat olur; hiç olmaması da serbesttir. Ör. öğle arasından sonra tek ders kalmasın.",
        CardRelationship.MAX_CONSECUTIVE: "Kümedeki dersler bir günde art arda en fazla N saat sürer.",
        CardRelationship.MAX_GAPS_PER_DAY: "Kümenin (sınıf/öğretmen) günlük programında en fazla N boş saat olur.",
        CardRelationship.MAX_GAP_LENGTH: "Boşluklar en fazla N saat uzunluğunda olur. Ör. öğretmen 2 saatlik boşluk yaşamasın: N=1.",
        CardRelationship.MAX_DISTINCT_PERIODS: "Kartlar hafta boyunca en fazla N farklı ders saatinde başlar. N=1: ders her gün aynı saatte.",
        CardRelationship.MAX_SAME_PERIOD_DAYS: "Aynı ders saatine en fazla N gün düşer. Ör. Matematik her gün 1. saatte olmasın: N=1 ya da 2.",
        CardRelationship.NOT_SIMULTANEOUS: "Kümedeki kartlar aynı saate düşmez. Ör. aynı malzemeyi kullanan iki ders ya da iki öğretmen.",
        CardRelationship.MAX_PER_POSITION: "Her saatte kümeden en fazla N kart olur. Ör. 5 matematik öğretmeninden her saatte en az biri boşta: N=4.",
        CardRelationship.MIN_PER_POSITION: "İşaretli her saatte kümeden en az N kart olur. Ör. her saatte en az 2 nöbetçi öğretmen dersi.",
        CardRelationship.SAME_TIME: "Seçilen derslerin kartları eşleşip aynı saate konur (1. kart ile 1. kart…). Ör. 5A ve 5B Matematik aynı anda.",
        CardRelationship.SAME_DAY: "Seçilen derslerin eşleşen kartları aynı güne konur.",
        CardRelationship.CONSECUTIVE: "Seçilen derslerin eşleşen kartları aynı gün art arda (bitişik) olur; sıra serbesttir.",
        CardRelationship.CONSECUTIVE_ORDERED: "Eşleşen kartlar aynı gün art arda olur ve ilk seçilen ders önce gelir. Ör. teori ve ardından laboratuvar.",
        CardRelationship.AB_NOT_SAME_DAY: "A tarafındaki hiçbir kart B tarafındaki bir kartla aynı güne düşmez. Haritalarla: ör. öğretmen aynı gün hem sabah (A haritası) hem öğleden sonra (B haritası) ders vermesin.",
        CardRelationship.AB_NOT_CONSECUTIVE: "A ve B kartları art arda gelmez. Ör. iki zor ders üst üste olmasın.",
        CardRelationship.AB_NOT_DAY_AFTER: "B kartı, A kartının ertesi gününe düşmez. Ör. Biyoloji Kimya'dan sonraki gün olmasın (A: Kimya, B: Biyoloji).",
        CardRelationship.ROOM_MAX_WEEK: "Kümenin seçili dersliklerdeki dersleri haftada en fazla N saat olur. Ör. bodrum spor salonu haftada en fazla 5 kez.",
        CardRelationship.ROOM_MIN_WEEK: "Kümenin seçili dersliklerde haftada en az N saati olur. Ör. her grup haftada en az bir kez büyük spor salonunda.",
        CardRelationship.MAX_ROOMS_WEEK: "Kümenin dersleri haftada en fazla N farklı dersliğe yayılır. Ör. Biyoloji'nin 3 saati hep aynı laboratuvarda: N=1.",
        CardRelationship.MAX_BUILDINGS_DAY: "Küme bir günde en fazla N farklı binada ders görür.",
        # Gün yayılımı ve boşluklar
        CardRelationship.DAY_SPAN_MAX: "İlk dersten son derse kadar geçen süre (boşluklar dahil) en fazla N saat olur. Ör. öğretmen okulda günde en fazla 6 saat kalsın.",
        CardRelationship.DAY_SPAN_MIN: "Ders olan günlerde ilk dersten son derse en az N saat olur; boş günler serbesttir. Ör. tek derse gelinmesin.",
        CardRelationship.MIN_PER_DAY: "Her gün (harita verilirse işaretli saatlerde) en az N saat ders olur; boş gün olmaz.",
        CardRelationship.MIN_GAP_LENGTH: "Gün içinde boşluk olacaksa en az N saat sürer. Ör. N=2: tek saatlik boşluk olmasın, olacaksa 2 saat olsun.",
        CardRelationship.MIN_DISTANCE: "Aynı gündeki iki kart arasında en az N boş saat olur. Ör. iki sınav arasında en az 1 saat ara.",
        CardRelationship.GAPS_FROM_START: "Günlük boş saat sınırı; ilk dersten önceki boş saatler de sayılır (gün 1. saatten başlamış sayılır).",
        CardRelationship.GAPS_TO_END: "Günlük boş saat sınırı; son dersten sonra gün sonuna kadar boş saatler de sayılır.",
        CardRelationship.MAX_GAPS_WEEK: "Haftanın tüm günlerindeki boş saatlerin toplamı en fazla N olur.",
        CardRelationship.GAPS_WEEK_FROM_START: "Haftalık boş saat sınırı; her günün ilk dersinden önceki boşluklar da sayılır.",
        CardRelationship.GAPS_WEEK_TO_END: "Haftalık boş saat sınırı; her günün son dersinden sonraki boşluklar da sayılır.",
        CardRelationship.MAX_CONSEC_DAYS: "Ders olan günler en fazla N gün art arda gelir. Ör. N=2: Pzt-Sal olur, Pzt-Sal-Çar olmaz.",
        CardRelationship.MAX_FREE_DAYS: "İki ders günü arasında en fazla N boş gün olur. Ör. N=1: Pazartesi'den sonra en geç Çarşamba.",
        # A/B sıralama
        CardRelationship.AB_AFTER: "Aynı gün hem A hem B varsa A'nın tüm dersleri B'nin tüm derslerinden sonra gelir. Ör. teori (B) önce, uygulama (A) sonra.",
        CardRelationship.AB_BEFORE: "Aynı gün hem A hem B varsa A'nın tüm dersleri B'nin tüm derslerinden önce gelir.",
        CardRelationship.AB_NOT_MIXED: "Aynı gün A ve B dersleri iç içe geçmez: A'lar ya hep önce ya hep sonra.",
        CardRelationship.AB_WEEK_BEFORE: "Hafta boyunca tüm A dersleri, B derslerinin hepsinden önce yerleşir.",
        CardRelationship.AB_DAY_BEFORE: "A'nın ders günleri B'nin ders günlerinden önce gelir. Ör. A haftanın başında, B sonunda.",
        CardRelationship.AB_MAX_CONSECUTIVE: "A ve B dersleri birlikte sayıldığında art arda en fazla N saat olur.",
        CardRelationship.AB_FILL_GAPS: "A'nın gün içindeki boşlukları B dersleriyle doldurulur. Ör. öğretmenin boşluklarına etüt (B) gelsin.",
        CardRelationship.AB_A_FIRST: "B'nin olduğu günlerde B'den önce en az bir A dersi olur.",
        CardRelationship.AB_B_AFTER: "A'nın olduğu günlerde A'dan sonra en az bir B dersi olur.",
        CardRelationship.AB_NOT_FOLLOWED: "A'nın hemen ardından B gelmez (ters sıra serbest). Ör. Beden Eğitimi'nin hemen ardından Matematik olmasın.",
        # Başlama ve bitiş
        CardRelationship.ONLY_IN_MAP: "Seçilen kartlar yalnızca haritada işaretli saatlere yerleşir (her saati işaretli hücrede olmalı). Ör. atölye dersleri yalnızca öğleden sonra.",
        CardRelationship.NO_START_AT: "Seçilen kartlar haritada işaretli saatlerde başlamaz. Ör. blok dersler öğle arasından hemen önce başlamasın.",
        CardRelationship.NO_END_AT: "Seçilen kartlar haritada işaretli saatlerde bitmez.",
        CardRelationship.FIRST_OR_LAST: "Her kart ya günün ilk saatinde başlar ya da son saatinde biter. Ör. dışarıdan gelen öğretmenin dersleri.",
        CardRelationship.RESERVE: "Haritada işaretli saatler seçilen derslere ayrılır: aynı sınıfların diğer dersleri bu saatlere konmaz.",
        # Farklılık sayıları
        CardRelationship.MAX_SUBJECTS_WEEK: "Kümede haftada (harita verilirse işaretli saatlerde) en fazla N farklı ders adı olur.",
        CardRelationship.MAX_SUBJECTS_DAY: "Kümede bir günde en fazla N farklı ders adı olur. Ör. sınıfın günde en fazla 4 farklı dersi.",
        CardRelationship.MAX_TEACHERS_DAY: "Kümede bir günde en fazla N farklı öğretmen ders verir.",
        CardRelationship.MAX_ROOMS_DAY: "Küme bir günde en fazla N farklı derslik kullanır.",
        CardRelationship.MAX_ROOM_CHANGES: "Küme bir günde en fazla N kez derslik değiştirir (farklı derslik sayısı − 1 olarak sayılır).",
        CardRelationship.MAX_BUILDING_CHANGES: "Küme bir günde en fazla N kez bina değiştirir (farklı bina sayısı − 1 olarak sayılır).",
        CardRelationship.MAX_BUILDINGS_WEEK: "Küme haftada en fazla N farklı binada ders görür.",
        CardRelationship.MAX_ROOMS_POSITION: "Kümenin aynı saatte kullandığı derslik sayısı en fazla N olur.",
        # Öğrenci
        CardRelationship.ST_SAME_TEACHER: "Seçmeli dağıtımında öğrenci, seçilen derslerin şubelerinde aynı öğretmene düşer. Program üretiminde değil, Öğrenciler → Dağıt'ta uygulanır.",
        CardRelationship.ST_DIFF_TEACHER: "Seçmeli dağıtımında öğrenci, seçilen derslerin şubelerinde aynı öğretmene iki kez düşmez.",
        CardRelationship.ST_TEACHER_IN: "Seçmeli dağıtımında öğrenci bu derslerde yalnızca “öğretmenler” alanında seçilenlerin şubelerine yerleşir.",
        CardRelationship.ST_TEACHER_NOT_IN: "Seçmeli dağıtımında öğrenci bu derslerde “öğretmenler” alanında seçilenlerin şubelerine yerleşmez.",
        CardRelationship.ST_SAME_GROUP: "Seçilen seçmelilerde aynı şubeye düşen öğrenciler diğer seçmelide de aynı şubede toplanır (dağıtım tercih eder).",
        CardRelationship.ST_TERM_BEFORE: "Hem A hem B'yi seçen öğrenci A şubesini B'den önceki dönemde alır.",
        CardRelationship.ST_TERM_BEFORE_SAME: "Hem A hem B'yi seçen öğrenci A'yı B'den önce ya da aynı dönemde alır.",
        CardRelationship.ST_SAME_TERM: "Hem A hem B'yi seçen öğrenci ikisini aynı dönemde alır.",
        CardRelationship.ST_DIFF_TERM: "Hem A hem B'yi seçen öğrenci ikisini aynı dönemde almaz.",
        CardRelationship.ST_MIN_ELECTIVES: "Öğrenci seçilen derslerden en az N tanesini seçmiş olmalı; eksik seçimler Öğrenciler ekranında uyarı olarak çıkar.",
        CardRelationship.ST_MAX_ELECTIVES: "Öğrenci seçilen derslerden en fazla N tanesini seçebilir; fazlası uyarı olarak çıkar.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("lessons", "lessons_b"):
            self.fields[name].queryset = self.fields[name].queryset.select_related("subject").prefetch_related("classes")
        self.fields["teachers"].label_from_instance = lambda t: f"{t.first_name} {t.last_name}"
        for name in ("subjects", "subjects_b"):
            self.fields[name].label_from_instance = lambda s: s.name
        self.fields["card_length"].widget.attrs["class"] = "select"
        condition = self.fields["condition"].widget
        condition.attrs.update(
            {
                "data-uses-n": " ".join(sorted(CardRelationship.USES_N)),
                "data-uses-map": " ".join(sorted(CardRelationship.USES_MAP)),
                "data-needs-map": " ".join(sorted(CardRelationship.NEEDS_MAP)),
                "data-paired": " ".join(sorted(CardRelationship.PAIRED)),
                "data-two-sided": " ".join(sorted(CardRelationship.TWO_SIDED)),
                "data-rooms": " ".join(sorted(CardRelationship.ROOMS)),
                "data-student": " ".join(sorted(CardRelationship.STUDENT)),
                "data-soft-target": " ".join(sorted(CardRelationship.SOFT_TARGET)),
                "data-help": json.dumps(self.CONDITION_HELP, ensure_ascii=False),
            }
        )
        self.map_meta = {
            "days": self.school.day_names,
            "periods": [{"name": p.name, "start": p.start_time.strftime("%H:%M") if p.start_time else ""} for p in self.school.periods.all()],
        }

    def _clean_map(self, name):
        value = self.cleaned_data.get(name) or []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise ValidationError("Zaman haritası okunamadı.")
        days, periods = self.school.days_per_week, self.school.periods.count()
        cells = []
        for item in value if isinstance(value, list) else []:
            try:
                d, p = (int(x) for x in str(item).split("-"))
            except ValueError:
                continue
            if 0 <= d < days and 0 <= p < periods:
                cells.append(f"{d}-{p}")
        return sorted(set(cells), key=lambda c: tuple(int(x) for x in c.split("-")))

    def clean_time_map(self):
        return self._clean_map("time_map")

    def clean_time_map_b(self):
        return self._clean_map("time_map_b")

    def clean(self):
        data = super().clean()
        condition = data.get("condition")
        if condition in CardRelationship.PAIRED and len(data.get("lessons") or []) < 2:
            self.add_error("lessons", "Bu koşul seçilen derslerin kartlarını eşleştirir; en az iki ders seçin.")
        if condition in CardRelationship.TWO_SIDED and not (data.get("lessons_b") or data.get("subjects_b")):
            self.add_error("subjects_b", "İki taraflı koşul için B tarafında ders ya da ders adı seçin.")
        if condition in CardRelationship.ROOMS and not data.get("classrooms"):
            self.add_error("classrooms", "Bu koşul için en az bir derslik seçin.")
        if data.get("param_max") is not None:
            if condition not in CardRelationship.SOFT_TARGET:
                data["param_max"] = None
            elif data["param_max"] <= data.get("param", 0):
                self.add_error("param_max", "İstisna üst sınırı N'den büyük olmalı.")
        if condition in CardRelationship.TEACHER_LIST and not data.get("teachers"):
            self.add_error("teachers", "Bu koşul için öğretmenler alanında en az bir öğretmen seçin.")
        if condition in CardRelationship.NEEDS_MAP and not data.get("time_map"):
            self.add_error("time_map", "Bu koşul için zaman haritasında en az bir hücre işaretleyin.")
        if condition in (CardRelationship.MAX_DAYS, CardRelationship.MIN_DAYS) and data.get("param", 0) > self.school.days_per_week:
            self.add_error("param", f"Okulda haftada {self.school.days_per_week} gün var.")
        return data
