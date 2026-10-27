"""Veri giriş formları. Tüm seçim alanları ilgili okulun kayıtlarıyla sınırlanır."""

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
        fields = ["name", "days_per_week", "weeks_count", "terms_count"]
        widgets = {"days_per_week": forms.Select(choices=[(n, f"{n} gün ({', '.join(DAY_NAMES[:n])})") for n in range(1, 8)])}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["weeks_count"].widget = forms.Select(choices=[(1, "Her hafta aynı"), (2, "İki haftalık (A/B)")])
        self.fields["terms_count"].widget = forms.Select(choices=[(1, "Tek dönem"), (2, "İki dönem")])
        self._style()


class PeriodForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Period
        fields = ["name", "start_time", "end_time"]
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
    class Meta:
        model = Subject
        fields = ["name", "short", "color"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class BuildingForm(SchoolScopedForm):
    class Meta:
        model = Building
        fields = ["name"]


class TeacherForm(SchoolScopedForm):
    class Meta:
        model = Teacher
        fields = ["first_name", "last_name", "short", "max_periods_per_day", "max_gaps_per_day", "max_gaps_per_week", "max_days_per_week"]
        help_texts = {
            "max_periods_per_day": "Boş = sınır yok",
            "max_gaps_per_day": "Boş = sınır yok",
            "max_gaps_per_week": "Boş = sınır yok",
            "max_days_per_week": "Ör. 4 = haftada bir boş gün",
        }


class ClassroomForm(SchoolScopedForm):
    scoped = {"building": (Building, "school")}

    class Meta:
        model = Classroom
        fields = ["name", "short", "capacity", "building"]


class SchoolClassForm(SchoolScopedForm):
    scoped = {"home_classroom": (Classroom, "school")}

    class Meta:
        model = SchoolClass
        fields = ["name", "grade", "home_classroom"]
        help_texts = {"home_classroom": "Derslik seçilmemiş tek sınıflık dersler bu derslikte yapılır."}


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
        fields = ["subject", "classes", "groups", "teachers", "classrooms", "periods_per_week", "card_length", "max_per_day", "weeks_mask", "terms_mask"]
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
        self.fields["classes"].required = True
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
        periods = self.school.periods.count()
        if data.get("card_length") and periods and data["card_length"] > periods:
            self.add_error("card_length", f"Kart uzunluğu günlük ders saatinden ({periods}) uzun olamaz.")
        if data.get("periods_per_week") == 0:
            self.add_error("periods_per_week", "Haftalık saat en az 1 olmalı.")
        return data


class RelationshipForm(SchoolScopedForm):
    scoped = {
        "lessons": (Lesson, "school"),
        "subjects": (Subject, "school"),
        "classes": (SchoolClass, "school"),
        "teachers": (Teacher, "school"),
    }

    class Meta:
        model = CardRelationship
        fields = ["name", "active", "condition", "param", "apply_to", "importance", "subjects", "lessons", "classes", "teachers"]
        widgets = {
            "subjects": ChipSelectMultiple(),
            "lessons": ChipSelectMultiple(),
            "classes": ChipSelectMultiple(),
            "teachers": ChipSelectMultiple(),
        }
        help_texts = {
            "param": "“Günde en fazla N” ve “art arda en fazla N” kuralları için.",
            "importance": "Kesin kurallar mutlaka sağlanır; diğerleri ihlal edilirse ceza puanı eklenir.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lessons"].queryset = self.fields["lessons"].queryset.select_related("subject").prefetch_related("classes")
        self.fields["teachers"].label_from_instance = lambda t: f"{t.first_name} {t.last_name}"

    def clean(self):
        data = super().clean()
        if data.get("condition") == CardRelationship.SAME_TIME and len(data.get("lessons") or []) < 2:
            self.add_error("lessons", "“Aynı anda” kuralı için en az iki ders seçin.")
        return data
