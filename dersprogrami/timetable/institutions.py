"""Kurum sayfası: kurumun programları, yeni program, aSc'den içe aktarma ve program silme."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import access, asc_xml
from .counts import with_program_counts
from .data_views import default_periods
from .models import DutyPlace, Institution, Period, ReportPreset, School

MAX_UPLOAD = 20 * 1024 * 1024


def _programs(request, institution):
    visible = access.visible_schools(request.user).filter(institution=institution)
    return with_program_counts(visible).select_related("active_timetable").order_by("name")


def institution_detail(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    perms = access.institution_permissions(request.user, institution)
    programs = list(_programs(request, institution))
    from .copying import PARTS

    return render(request, "timetable/institution.html", {
        "institution": institution, "programs": programs, "nav": "institution", "copy_parts": PARTS,
        "can_programs": "programlar" in perms, "can_users": "kullanici" in perms,
    })


@require_POST
def program_new(request, pk):
    institution = get_object_or_404(Institution, pk=pk)
    name = (request.POST.get("name") or "").strip()[:200]
    if not name:
        messages.error(request, "Program adı girin.")
        return redirect("timetable:institution_detail", pk=institution.pk)
    source = institution.programs.filter(pk=request.POST.get("copy_periods") or 0).first()
    with transaction.atomic():
        school = School.objects.create(
            institution=institution, name=name,
            days_per_week=source.days_per_week if source else 5,
        )
        if source:
            Period.objects.bulk_create(
                Period(school=school, index=p.index, name=p.name, start_time=p.start_time, end_time=p.end_time,
                       long_break_after=p.long_break_after)
                for p in source.periods.all()
            )
        else:
            default_periods(school)
    messages.success(request, f"“{school}” programı oluşturuldu. Kurulum sihirbazı verileri adım adım ister.")
    return redirect("timetable:setup_wizard_start", pk=school.pk)


@require_POST
def program_import(request, pk):
    """aSc TimeTables XML'i kurumun içine aktarır: yeni program olarak, seçilen programı güncelleyerek
    (mode="update", varsayılan; elle girilen veri korunur, bkz. asc_merge) ya da programın yerine
    (mode="replace"; eski program silinir)."""
    from . import asc_merge

    institution = get_object_or_404(Institution, pk=pk)
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Dosya seçilmedi.")
        return redirect("timetable:institution_detail", pk=institution.pk)
    if upload.size > MAX_UPLOAD:
        messages.error(request, "Dosya çok büyük (en fazla 20 MB).")
        return redirect("timetable:institution_detail", pk=institution.pk)
    target = request.POST.get("target") or "new"
    mode = "replace" if request.POST.get("mode") == "replace" else "update"
    old = None
    if target != "new":
        old = get_object_or_404(School, pk=target, institution=institution)
        if not access.school_permissions(request.user, old):
            messages.error(request, "Bu programa erişim yetkiniz yok.")
            return redirect("timetable:institution_detail", pk=institution.pk)
    given_name = (request.POST.get("name") or "").strip()
    name = given_name or (old.name if old else upload.name.rsplit(".", 1)[0])
    try:
        if old is not None and mode == "update":
            with transaction.atomic():
                timetable, summary = asc_merge.merge_into(old, upload.read())
                if given_name and given_name[:200] != old.name:
                    old.name = given_name[:200]
                    old.save(update_fields=["name"])
            school = old
        else:
            with transaction.atomic():
                school, timetable = asc_xml.import_school(upload.read(), name=name, institution=institution)
                school.name = name[:200]
                school.save(update_fields=["name"])
                if old is not None:
                    _replace(old, school)
    except asc_xml.AscImportError as exc:
        messages.error(request, f"İçe aktarılamadı: {exc}")
        return redirect("timetable:institution_detail", pk=institution.pk)
    if old is not None and mode == "update":
        messages.success(request, f"“{school}” güncellenerek aktarıldı. {asc_merge.describe(summary)}")
    else:
        verb = "yerine aktarıldı" if old else "yeni program olarak aktarıldı"
        messages.success(request, f"“{school}” {verb}.")
    if timetable:
        return redirect("timetable:timetable_detail", pk=timetable.pk)
    return redirect("timetable:school_detail", pk=school.pk)


def _replace(old, new):
    """Eski programın kurumdaki bağlantılarını yenisine taşır ve eskisini siler."""
    for membership in old.restricted_memberships.all():
        membership.programs.add(new)
    new.linked_programs.set(old.linked_programs.all())
    ReportPreset.objects.filter(school=old).update(school=new)
    for place in DutyPlace.objects.filter(school=old):  # nöbet yerleri korunur; nöbetler yeni öğretmenlerle yeniden dağıtılır
        place.duties.all().delete()
        place.school = new
        place.save(update_fields=["school"])
    new.duties_per_teacher = old.duties_per_teacher
    new.save(update_fields=["duties_per_teacher"])
    old.delete()


@require_POST
def program_delete(request, pk):
    school = get_object_or_404(School, pk=pk)
    institution = school.institution
    if request.POST.get("confirm") != school.name:
        messages.error(request, "Silmek için program adını aynen yazın.")
        return redirect("timetable:school_settings", pk=school.pk)
    name = school.name
    school.delete()
    messages.success(request, f"“{name}” programı silindi.")
    return redirect("timetable:institution_detail", pk=institution.pk)


@require_POST
def program_copy(request, pk):
    """Programı kopyala: kaynak programın seçilen verisiyle aynı kurumda yeni program."""
    from . import copying

    institution = get_object_or_404(Institution, pk=pk)
    source = get_object_or_404(School, pk=request.POST.get("source"), institution=institution)
    if not access.school_permissions(request.user, source):
        messages.error(request, "Kaynak programa erişim yetkiniz yok.")
        return redirect("timetable:institution_detail", pk=institution.pk)
    name = (request.POST.get("name") or "").strip() or f"{source.name} (kopya)"
    asked = set(request.POST.getlist("parts"))
    school, parts = copying.copy_program(source, name, asked)
    added = parts - asked
    note = f" Bağımlı olduğu için şunlar da kopyalandı: {', '.join(copying.PARTS[p] for p in sorted(added))}." if added else ""
    messages.success(request, f"“{school}” oluşturuldu ({len(parts)} bölüm kopyalandı).{note}")
    return redirect("timetable:school_detail", pk=school.pk)
