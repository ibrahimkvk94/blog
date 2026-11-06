# Ders Programı (`timetable`) modülünün KAMYOSİS'e bütünleştirilmesi — analiz

> Hazırlanma: 2 Kasım 2026. Salt okuma incelemesi: iki depoda da hiçbir dosya değiştirilmedi, kod/test/migration
> çalıştırılmadı, paket kurulmadı.
>
> - **TT** = Ders Programı modülü: `C:\Users\USER\Desktop\DersProgrami\dersprogrami` (uygulama `timetable/`, bağımsız proje
>   `config/`), son commit `1fd6ac3`.
> - **KM** = KAMYOSİS: `C:\Users\USER\Desktop\KAMYOSIS` (Django 5.2.18, Python 3.13.5), son commit `cb6c635`.
>
> Satır numaraları inceleme anındaki dosyalara göredir.

---

## 0. Kısa sonuç

**Önerilen mimari:** TT, KM ile **aynı Django projesinde** ayrı bir uygulama olarak çalışır (MODUL-DEVIR §8 "Seçenek A").
Adresi `/ders-programi/` olur, ilk aşamada kendi arayüz kabuğunu korur. Yeni ve küçük bir **köprü uygulaması**
(`dersprogrami_kopru`) şu işleri yapar:

1. Okulun tamamı için **tek bir `Institution`** açar ve TT `Membership` kayıtlarını KM'deki `Yetki`/`Birim` ağacından
   **türetip eşitler**. Kullanıcı yönetimi yalnızca KM'de yapılır.
2. Bağımsız kuruluma ait tehlikeli rotaları kapatır: sistem güncelleme, yedek geri yükleme, yedekle karşılaştırma,
   kurum/hesap açma.
3. Programı KM'ye gönderir: TT'nin aSc XML dışa aktarıcısının çıktısı, kimlikleri kalıcılaştırıldıktan sonra süreç
   içinde KM'nin `program.asc.ice_aktar()` fonksiyonuna verilir. Sonuç bir **taslak `ProgramSurumu`** olur, yayını yine
   KM'deki yetkili yapar.

**Kritik bulgular (yapılmazsa veri kaybı ya da güvenlik açığı doğar):**

| # | Bulgu | Nerede |
|---|---|---|
| K1 | KM'de `LoginRequiredMiddleware` **yok**. TT görünümlerinin neredeyse hiçbirinde `@login_required` yok; TT bu ara katmana güveniyor. Eklenmezse TT sayfaları girişsiz açılır | KM `config/settings.py:47-58`, TT `docs/MODUL-DEVIR.md:179-184` |
| K2 | Yedekten geri yükleme `flush` komutunu **tüm veritabanında** çalıştırır, yani KM'nin bütün verisini siler | TT `timetable/backup.py:97-107` (`call_command("flush")` satır 103) |
| K3 | "Yedekle karşılaştır" bir alt süreçte `manage.py migrate` ve `loaddata` çalıştırır, hedef veritabanını `DJANGO_DB_PATH` ortam değişkeniyle seçer. KM bu değişkeni okumaz (`KAMYOSIS_DB` kullanır). Sonuç olarak yedek **canlı KM veritabanına** yüklenir. `test_backup_compare.py` KM içinde koşarsa aynısı olur | TT `backup.py:117-150` (env satır 130, manage satır 132) |
| K4 | Sistem güncelleme, KM kök klasöründe (`settings.BASE_DIR`) `git pull` ve `git reset --hard` çalıştırır, ardından `os._exit(3)` ile sunucuyu öldürür. KM'de sunucuyu yeniden başlatacak bir başlatıcı yok | TT `updater.py:21-30, 75-99` |
| K5 | 19 model alanı `"auth.User"` dizesini doğrudan kullanıyor. `AUTH_USER_MODEL="accounts.User"` olduğu için sistem denetimi (fields.E301) hata verir ve proje açılmaz | §2 |

**Tahmini çekirdek iş:** 8,5–11 iş günü (§9). İsteğe bağlı görsel uyum ve örtüşme köprüleri için ayrıca 3–7 gün.

---

## 1. Envanter

### 1.1 Modeller ve özellikler

TT'de 39 model var: `timetable/models.py` içinde 35, `timetable/exam_models.py` içinde 4. Adlandırılmış URL sayısı yaklaşık
142 (`timetable/urls.py`, ad alanı `timetable`).

| Alan | Modeller | Ne yapar | Ana dosyalar |
|---|---|---|---|
| Kurum ve yetki | `Institution` (20), `Membership` (1262), `AuditLog` (1337) | Çok kurumlu yapı, kurum düzeyinde yetki listesi, işlem günlüğü | `access.py`, `accounts.py`, `institutions.py` |
| Program dosyası | `School` (39): tarihsel adı bu, arayüzde "program" diye geçer | Dönemlik program: gün sayısı, A/B haftası, dönem, yayın anahtarı, `active_timetable`, `working_timetable` | `views.py`, `data_views.py` |
| Temel veri | `Period`, `Building`, `Classroom`, `Subject`, `Teacher` (tc_no, email, user), `SchoolClass`, `Division`, `Group`, `Lesson`, `Availability`, `CardRelationship` (817), `Student` | aSc'deki veri girişinin karşılığı, kart ilişkileri (kurallar) | `data_views.py`, `setup_wizard.py`, `importer.py`, `asc_xml.py`, `asc_merge.py` |
| Üretim | `Timetable` (631), `Card` (720), `TimetableVersion` (793), `ImproveJob` (752) | CP-SAT ile üretim, onarım, ceza düşürme, sürümler ve geri al | `solver/` (Django'dan bağımsız), `services.py`, `jobs.py`, `school_improve.py`, `quick_jobs.py` |
| Üretim sonrası | — | Sürükle-bırak düzenleme, çözüm merkezi, kalite karnesi, karşılaştırma, raporlar, PDF ve Excel | `editing.py`, `grid.py`, `resolve.py`, `quality.py`, `report_*.py`, `printing.py` |
| Günlük işler | `Absence` (1116), `Substitution` (1140), `Event` (1161), `DutyPlace` (1207), `Duty` (1229) | Vekâlet, etkinlik ve telafi dersi, derslik ayırma, haftalık nöbet | `substitutes.py`, `events.py`, `duty.py` |
| Sınav | `ExamPeriod`, `Exam`, `ExamPlacement`, `ExamRoom` | Vize, final ve bütünleme programı; salon ve gözetmen ataması (ayrı CP-SAT modeli) | `exams.py`, `exams_solver.py`, `exam_views.py`, `exam_excel.py` |
| Öğretmen tarafı | `LeaveRequest`, `AvailabilityRequest`, `TeacherQuota`, `Department`, `DepartmentSubmission` | Öğretmen hesapları, "Programım", istekler, bölüm sorumlusu önerileri | `teacher_accounts.py`, `teacher_requests.py`, `teacher_calendar.py`, `departments.py` |
| Dış dünya | `LessonRef`, `WeekArchive` | ÜYBS aktarımı, web yayını (girişsiz), .ics takvim, e-posta | `uybs.py`, `refs.py`, `public.py`, `notify.py` |
| Diğer | `ReportPreset`, `EditPresence`, `Notification` | Rapor şablonları, eşzamanlı düzenleme, uygulama içi bildirim | `concurrency.py`, `notifications.py` |

### 1.2 Bağımlılıklar (TT `requirements.txt`)

| Paket | KM'de var mı | Not |
|---|---|---|
| `Django>=5.2,<6` | Var (`>=5.2,<5.3`, kurulu 5.2.18) | Uyumlu |
| `ortools>=9.12` | **Yok** | **Ağır paket.** Beraberinde numpy, pandas, protobuf, absl-py ve immutabledict gelir; toplam yaklaşık 150–200 MB. Ayrıntı §8 |
| `openpyxl>=3.1` | Var | — |
| `reportlab>=4` | Yok | PDF çıktısı. DejaVu fontları modülle birlikte geliyor (`timetable/fonts/`) |
| `segno>=1.6` | Yok | QR kodu (`public.py`) |
| `whitenoise>=6.7`, `waitress>=3` | Var | — |
| `tzdata` | — | Windows'ta saat dilimi için. Eklenmesi zararsız |
| `gunicorn`, `psycopg[binary]` | — | KM'de gerekmez (Linux / PostgreSQL için) |

### 1.3 Ayarlar ve ara katmanlar (TT `config/settings.py`)

| Gereken | TT'deki yeri | KM'deki durum |
|---|---|---|
| `django.contrib.auth.middleware.LoginRequiredMiddleware` (Django 5.1 ve sonrası) | `settings.py:57` | **Yok (K1)**. Eklenmesi KM için güvenli: KM görünümleri zaten `@login_required` ya da `yetki_gerekli` ile korunuyor. Django 5.1+ sürümünde `LoginView` ve yönetim girişi `login_not_required` olarak işaretli |
| `timetable.access.SchoolAccessMiddleware` (`AuthenticationMiddleware` sonrasında, `MessageMiddleware` öncesinde) | `settings.py:58` | Eklenecek. `process_view` yalnızca `namespace == "timetable"` olan isteklerde çalışır (`access.py:268-270`) |
| `TEMPLATES OPTIONS builtins = ["timetable.templatetags.search"]` (`fold` süzgeci) | `settings.py:75` | Eklenecek |
| Bağlam işlemcisi `timetable.access.can` | `settings.py:80` | Eklenecek. Not: KM'nin **her** sayfasında 2 küçük sorgu çalıştırır (`access.py:325-329`). İstenirse yalnızca `timetable` ad alanında çalışan bir sarmalayıcıyla sınırlanır |
| `TIMETABLE_SOLVER_TIME_LIMIT`, `PUBLIC_URL`, `BACKUP_DIR`, `BACKUP_KEEP` | 39, 156, 164-165 | `getattr` ile değil doğrudan okunuyor; **tanımlanmaları zorunlu** |
| `TIMETABLE_RUN_IN_BACKGROUND`, `TIMETABLE_JOB_BACKEND`, `AUTO_BACKUP`, `EMAIL_HOST` | 158-177 | `getattr` ile, varsayılanlı okunuyor. KM'de `AUTO_BACKUP = False` yapılmalı |
| `LOGIN_URL = "timetable:login"` | 151-153 | KM'nin `"login"` değeri korunur |
| SQLite `OPTIONS` (WAL, `transaction_mode=IMMEDIATE`, 20 sn bekleme) | 105-116 | KM'de **yok** (`settings.py:80-86`). §8'e bakın |
| `apps.ready()`: giriş ve başarısız giriş sinyalleri, problem önbelleği sinyalleri | `apps.py` | Her KM girişi TT `AuditLog` tablosuna da yazılır (zararsız) |

### 1.4 Statik dosyalar ve JS

- `timetable/static/timetable/`: `app.css` (1880 satır) ve 16 sade JS dosyası. **CDN yok, derleme adımı yok.** Sürüm
  eki `{% asset %}` etiketiyle üretiliyor (`templatetags/assets.py`, `finders.find` kullanıyor; `collectstatic` ile
  uyumlu).
- KM ise Bootstrap 5.3.3, Bootstrap Icons ve Tom Select'i **CDN'den** yüklüyor (KM `templates/base.html:10-12, 107-108`).
  TT sayfaları kendi kabuğunda kaldıkça bu fark sorun çıkarmaz.

### 1.5 Yönetim komutları (`timetable/management/commands/`)

| Komut | İş | KM'de |
|---|---|---|
| `calisan` | `worker` kipinde iş kuyruğunu işleyen ayrı süreç | Kullanılacak (karar 3) |
| `generate_timetable` | Komut satırından üretim | Kalabilir |
| `girdi_ozeti` | Yedek karşılaştırmanın alt süreci | Kullanılmamalı |
| `seed_demo` | Örnek okul | Yalnızca geliştirme ortamında |
| `sunucu` | waitress ile yayın ve otomatik yedek döngüsü | **Kullanılmamalı.** KM `yayinla.py` kullanıyor |
| `yedekle` | Tüm veritabanının JSON dökümü | **Kullanılmamalı.** Bütün KM verisini döker |

Komut adları KM'deki komutlarla (`access_aktar`, `personel_liste_aktar`, `asc_aktar`, `program_tanim_guncelle`)
çakışmıyor.

### 1.6 Arka plan işleri

| İş | Kip | Kod |
|---|---|---|
| Program üretimi | `thread`: web sürecinde iş parçacığı. `worker`: veritabanı kuyruğu + `manage.py calisan` | `jobs.py:72-89`, `services.py:340` |
| Okul geneli iyileştirme, "İhlalleri çöz", "Cezayı düşür" | Aynı ayar (`ImproveJob` kuyruğu) | `school_improve.py:47-52`, `quick_jobs.py:89-92` |
| Sınav çözümü | **Her zaman** web sürecinde iş parçacığı (kuyruk yok) | `exams.py:395-410` |
| Yedek karşılaştırma | Web sürecinde iş parçacığı + alt süreç | `backup.py:158-177` |
| Güncelleme sonrası yeniden başlatma | İş parçacığı + `os._exit` | `updater.py:89-99` |

Çözücü iş parçacığı sayısı `SOLVER_WORKERS` ortam değişkeniyle belirlenir. Değişken yoksa `min(32, max(8, çekirdek))`
kullanılır (`solver/cpsat.py:31-38`). Bu bilgisayarda 4 çekirdek var, yani varsayılanda 8 iş parçacığı açılır.

---

## 2. Kullanıcı modeli bağımlılığı

### 2.1 Değişmesi zorunlu yerler (uygulama kodu)

| Dosya:satır | Şu an | Olması gereken |
|---|---|---|
| `models.py:255` `Teacher.user` | `"auth.User"` | `settings.AUTH_USER_MODEL` |
| `models.py:503, 511` `LeaveRequest.requested_by/decided_by` | aynı | aynı |
| `models.py:560` `Department.users` (M2M) | aynı | aynı |
| `models.py:588, 591` `DepartmentSubmission.updated_by/decided_by` | aynı | aynı |
| `models.py:613, 618` `AvailabilityRequest.requested_by/decided_by` | aynı | aynı |
| `models.py:771` `ImproveJob.created_by` | aynı | aynı |
| `models.py:799` `TimetableVersion.user` | aynı | aynı |
| `models.py:1186` `Event.created_by` | aynı | aynı |
| `models.py:1285, 1293` `Membership.user/granted_by` | aynı | aynı |
| `models.py:1341` `AuditLog.user` | aynı | aynı |
| `models.py:1366` `EditPresence.user` | aynı | aynı |
| `models.py:1389` `WeekArchive.user` | aynı | aynı |
| `models.py:1435, 1440` `Notification.user/sender` | aynı | aynı |
| `exam_models.py:57` `ExamPeriod.requested_by` | aynı | aynı |
| `accounts.py:7` | `from django.contrib.auth.models import User` | `User = get_user_model()` |
| `notifications.py:7` | aynı | aynı |
| `request_views.py:6` | aynı | aynı |
| `teacher_accounts.py:19` | aynı | aynı |
| `forms.py:163` (fonksiyon içinde) | aynı | aynı |

Toplam 19 alan ve 5 içe aktarma. Bu sayı MODUL-DEVIR'deki "19 yer" bilgisiyle örtüşüyor.

- **Migration'lar zaten uyumlu.** 46 migration dosyasının hepsi `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`
  ve `to=settings.AUTH_USER_MODEL` kullanıyor (ör. `0010_versions.py:12,57`, `0012_memberships.py`). Alanlar düzeltildikten
  sonra `makemigrations` değişiklik üretmemeli. Bu, Faz 1'in kabul ölçütüdür.
- **Testler:** 74 test dosyasının 64'ü `from django.contrib.auth.models import User` kullanıyor. KM'de
  `User.objects` "swapped" hatası verir. Bunların `get_user_model()` yapılması mekanik bir değişiklik (Faz 4).

### 2.2 Kullanılan kullanıcı alanları

`username`, `email`, `first_name`, `last_name`, `get_full_name()`, `last_login`, `is_superuser`, `is_active`,
`create_user()`, `set_password` kullanılıyor (ör. `concurrency.py:59`, `teacher_accounts.py:106-121, 169`,
`versions.py:122`, `departments.py:353`). `accounts.User` `AbstractUser`'dan türediği için **hepsi mevcut**.

Ters erişim adları (`teacher_profiles`, `memberships`, `granted_memberships`, `departments`, `leave_requests`,
`availability_requests`, `notifications`) KM `User` üzerindeki `yetkiler`, `bolum` ve `personel` ile çakışmıyor.
Anlam karışıklığına dikkat: TT'deki `user.departments` TT `Department` kayıtlarını gösterir, KM'deki `user.bolum` ise
KM bölümünü.

TT'nin açtığı hesaplarda (`accounts.NewUserForm`, `teacher_accounts`) KM'nin `parola_degismeli` alanı doldurulmaz.
Bu ekranlar zaten kapatılacak (§7).

---

## 3. Yetki modeli

### 3.1 TT'de yetki nasıl işliyor

- `Institution` (kurum) altında birden çok `School` (program dosyası) bulunur. `School.save()` kurum verilmezse aynı
  adla yeni bir kurum açar (`models.py:100-104`).
- `Membership(user, institution, permissions: JSON listesi, programs: M2M kısıt)` (`models.py:1262-1312`).
  Kullanılabilen yetkiler: `goruntule`, `veri`, `program`, `yayin`, `vekalet`, `nobet`, `programlar`, `kullanici`.
  `perms` her zaman `goruntule` değerini de içerir (`models.py:1307`).
- `access.py` yetkiyi **tek noktada** denetler:
  - URL adından yetkiye giden tablolar: `SCHOOL_ROUTES` (26), `INSTITUTION_ROUTES` (86), `TIMETABLE_ROUTES` (94),
    `CARD_ROUTES` (132), `VERSION_ROUTES` (141). Her biri `(GET yetkisi, POST yetkisi)` çifti tutar.
    `OPEN_ROUTES` (143) giriş yapmış herkese açıktır, `CENTRAL_ROUTES` (146) yalnızca süper kullanıcıya.
    **Tabloda olmayan rota yalnızca süper kullanıcıya açılır** (279-280).
  - `school_permissions(user, school)` (153): süper kullanıcı her şeyi yapar. Diğerleri için kurum üyeliğine, varsa
    program kısıtına bakılır.
  - `institution_permissions(user, institution)` (171): programla sınırlı üye kurum düzeyinde yalnızca görüntüler.
  - `visible_schools` (186) ve `visible_institutions` (196): listelerde görünenler.
  - `SchoolAccessMiddleware.process_view` (268-303): rotanın türünden okulu bulur
    (`pk` → okul / program / kart / sürüm), yetkiyi hesaplar, `request.school_perms` değerini yazar, yetki yoksa 403 verir.
  - Bağlam işlemcisi `can(request)` (306): şablonlarda `{{ can.veri }}` gibi kullanılır.
- `Membership` tablosu `access.py` dışında da **doğrudan** sorgulanıyor:
  - `notifications.managers()` (`notifications.py:30-37`): bildirim alıcıları
  - `request_views.py:76, 138`: öğretmeni hesaba bağlama listesi
  - `forms.py:166`: öğretmen kartındaki hesap seçimi
  - `departments.can_edit` (`departments.py:114-116`)
  - `accounts.py`, `institutions.py`, `teacher_accounts.py:155`

### 3.2 KM'de yetki nasıl işliyor

`core.Birim` organizasyon ağacını, `core.Yetki(kullanici, birim, seviye 1/2/3, kapsam tum/bolum)` ise yetkiyi tutar.
`etkin_yetki(request, birim)` birimin kendisine ve üstlerine verilen yetkilerden en yükseğini döndürür
(`core/yetki.py:44-60`). `yetki_gerekli(slug, seviye)` görünümü bir birime bağlar (`core/yetki.py:119-134`).

İlgili birimler (`core/migrations/0002_baslangic_agaci.py`) ağaçta şöyle duruyor:

- Öğrenci İşleri Şube Müdürlüğü
  - Plan Program Kısmı (`plan-program`)
    - `ders-planlari`: `modul_url="program:ana"`
    - `sinav-planlari`: modül yok, durum "sırada"
- İdari İşler (`idari-isler`)
  - `nobet-gruplari`: `modul_url="nobet:ana"`

### 3.3 Seçenekler

| | **A. Membership'i Yetki'den türetmek (önerilen)** | B. `access.py` içine kanca |
|---|---|---|
| Fikir | Köprü uygulaması tek bir `Institution` tutar. Her kullanıcının `Membership.permissions` değeri, KM'deki etkin yetkiden hesaplanır ve sinyallerle güncel tutulur | `school_permissions`, `institution_permissions`, `visible_*` fonksiyonları ayardaki bir sağlayıcıya sorar |
| TT kodunda değişiklik | Yok. Yalnızca sınav için iki satırlık bir ek gerekir (§3.6) | 4 fonksiyon ve doğrudan `Membership` sorgulayan 6 yer (§3.1). Yapılmazsa bildirim alıcıları ve hesap listeleri boş kalır |
| Tutarlılık | Sinyal ve eşitleme komutu gerekir; ağaç değişince herkes yeniden hesaplanır | Her istekte canlı hesaplanır |
| Upstream (Codex gen2 çalışması) ile birleştirme | Kolay | Çatışma riski var |

**Öneri A.** Kullanıcı sayısı küçük (bir MYO). Eşitleme ucuz ve TT koduna dokunmadığı için upstream güncellemeleri
sorunsuz alınır.

### 3.4 Önerilen eşleme

TT'nin menü düğümü için yeni bir birim önerilir: `ders-programi`, "Ders Programı Hazırlama", türü `gorev`, `plan-program`
altında, `ders-planlari`'nın kardeşi olarak. `modul_url="timetable:school_list"` (parametresiz olduğu için `reverse`
çalışır). Neden kardeş: `ders-planlari`'na çocuk eklenirse menüde açılır grup haline gelir ve `program:ana`
bağlantısı kaybolur (`templates/partials/menu_dugum.html`). Yetki ağaçta aşağı geçtiği için `plan-program` ya da
şube düzeyinde yetkisi olanlar otomatik olarak kapsanır. Mevcut `ders-planlari` yetkilerinin bir veri migration'ıyla
kopyalanıp kopyalanmayacağı **karar 2**'dir.

| KM etkin yetki (birim `ders-programi`) | Kapsam | TT `Membership.permissions` |
|---|---|---|
| 0 (yok) | — | Membership silinir |
| 1 Görüntüleme | tum / bolum | `[]` (yalnız `goruntule`) |
| 2 Düzenleme | tum | `["veri", "vekalet"]` |
| 2 Düzenleme | bolum | `[]`. Ayrıca kullanıcının `bolum`'una karşılık gelen TT `Department.users` listesine eklenir; bölüm portalı ile öneri gönderebilir (isteğe bağlı, §6) |
| 3 Yönetim | tum | `["veri", "program", "yayin", "vekalet", "nobet", "programlar"]` |
| 3 Yönetim | bolum | Düzenleme/bölüm ile aynı |
| Süper kullanıcı | — | TT zaten her şeyi verir (`access.py:157-158`) |

`kullanici` (kullanıcı yönetimi) **hiç verilmez.** Kullanıcı ve yetki yalnızca KM yönetim panelinden yönetilir.

### 3.5 Köprünün yetki kodu (taslak)

```python
# dersprogrami_kopru/yetki.py
from types import SimpleNamespace
from django.conf import settings
from core.models import Yetki
from core.yetki import GORUNTULEME, DUZENLEME, YONETIM, birim_bul, etkin_yetki
from timetable.models import Institution, Membership as M

BIRIM = "ders-programi"
TAM = {GORUNTULEME: [], DUZENLEME: [M.DATA, M.SUBSTITUTE],
       YONETIM: [M.DATA, M.PROGRAM, M.PUBLISH, M.SUBSTITUTE, M.DUTY, M.PROGRAMS]}

def kurum():
    # Tek kurum: ilk kayıt; yoksa KURUM_ADI ile açılır (veri migration'ı da açabilir)
    return Institution.objects.order_by("pk").first() or Institution.objects.create(name=settings.KURUM_ADI)

def esitle(user):
    k = kurum()
    if not user.is_active or user.is_superuser:
        M.objects.filter(user=user, institution=k).delete()   # süper kullanıcıya TT zaten her şeyi verir
        return
    sahte = SimpleNamespace(user=user)          # etkin_yetki önbelleğini bu nesneye yazar
    seviye, kapsam = etkin_yetki(sahte, birim_bul(sahte, BIRIM))
    if seviye < GORUNTULEME:
        M.objects.filter(user=user, institution=k).delete()
        return
    perms = [] if kapsam == Yetki.BOLUM else TAM[seviye]
    M.objects.update_or_create(user=user, institution=k, defaults={"permissions": perms})
```

Tetikleyiciler:

- `post_save` ve `post_delete(Yetki)`: ilgili kullanıcı için `esitle(instance.kullanici)`
- `post_save(Birim)` (ağaç değişti): herkes için
- `post_save(User)`: `is_active` değiştiğinde
- Elle ya da başlangıçta çalıştırmak için `manage.py ders_programi_yetki_esitle`

`Institution` ilk kez bir veri migration'ıyla açılır. Yeni TT programları, kurum sayfasından
(`timetable:institution_detail` → `program_new` / `program_import`) **bu kuruma** eklenir.

### 3.6 Sınav yetkisi (`sinav-planlari`)

Sınav rotaları (`exams`, `exam_period`, `exam_solve`, `exam_results`, `exam_edit`, `exam_proctors`, `exam_print`,
`exam_excel`) TT'de `SCHOOL_ROUTES` içindedir: GET için `goruntule`, POST için `veri` ister (`access.py:76-83`).
Bunları KM'deki `sinav-planlari` yetkisine bağlamanın iki yolu var:

1. **Kapı:** Köprü ara katmanı `SchoolAccessMiddleware`'den **önce** çalışır. Sınav rotasında
   `etkin_yetki(request, birim_bul(request, "sinav-planlari"))` en az GORUNTULEME (GET) ya da DUZENLEME (POST)
   değilse `PermissionDenied` verir.
2. **Ek yetki:** Ders programında `veri` yetkisi olmayan bir sınav sorumlusunun POST yapabilmesi için TT'ye iki satırlık,
   upstream'e de önerilebilecek bir ek gerekir. `access.py:296` civarında:
   `perms = perms | getattr(request, "timetable_extra_perms", set())`. Köprü ara katmanı sınav rotalarında
   `request.timetable_extra_perms = {M.DATA}` yazar.

Sınav sorumlusunun programı görebilmesi için, eşitlemede `sinav-planlari` yetkisi olan kullanıcılara en az `goruntule`
üyeliği de verilmelidir. Bunun için `esitle` iki birimin yetkisinden en yükseğini kullanır.

`nobet-gruplari` **eşlenmemeli.** KM'deki nöbet ile TT'deki nöbet farklı kavramlar (§6).

---

## 4. Şablon ve arayüz

### 4.1 TT `templates/timetable/base.html` (144 satır)

- Tam sayfa iskelettir. Kendi sol menüsü (`{% sidebar_nav %}`) ve üst şerit menüsü (`{% ribbon_nav %}`) var; ikisi de
  `templatetags/navigation.py:NAV_GROUPS` listesinden yetkiye göre süzülerek üretilir. Bunlara Ctrl+K hızlı git,
  açık/koyu tema ve bildirim zili eklenir.
- Bloklar: `title`, `head`, `crumbs`, `heading`, `actions`, `content`, `scripts`. Sayfaların 63'ü bu şablonu genişletiyor.
  Yazdırma ve rapor şablonları (`print.html`, `report.html`, `duties_print.html`) bağımsız.
- Alt kısımda `timetable:account`, `timetable:central`, `timetable:logout`, `timetable:notifications` bağlantıları ve
  "Kurum kullanıcıları" bağlantısı var.

### 4.2 KM `templates/base.html` (166 satır)

Bootstrap 5.3.3 CDN'den yükleniyor. `{% block body %}` içinde `.uygulama > aside.kenar + .icerik-alani` yapısı var.
Kenar menüsü `core.context_processors.navigation` bağlam işlemcisinin `menu` değerinden üretiliyor. Bloklar: `title`,
`body`, `breadcrumb_ek`, `content`. Tom Select tüm `select.form-select` öğelerine otomatik uygulanıyor.

### 4.3 TT sayfaları doğrudan KM `base.html`'i genişletebilir mi?

**İlk aşamada önerilmez.** Nedenleri:

- `app.css` genel seçiciler tanımlıyor: `* , html, body, a, h1` (satır 29-35), `.sidebar` (42), `.main` (56), `.content` (68),
  `.btn` (99-102), `.alert` (126), `.table` (140-145). Bunlar Bootstrap'in `.btn`, `.alert` ve `.table` sınıflarıyla
  çakışır. Bootstrap ve `app.css` aynı sayfaya yüklenirse iki taraf da bozulur.
- TT'nin ana görünümü (ızgara, sürükle-bırak) tam genişlik ister ve kendi menüsüne (yaklaşık 30 sayfa) dayanır.
- Bağlam adları çakışmıyor: TT `can`, `school` ve `nav` kullanıyor, KM `menu`, `yol` ve `kisayollar` kullanıyor.
  Gerekirse birlikte çalışabilirler.

**Önerilen yol:** KM'nin `TEMPLATES["DIRS"]` klasörü uygulama şablonlarından önce arandığı için TT `base.html`'i, modül
dosyalarına dokunmadan **`KAMYOSIS/templates/timetable/base.html` ile ezilebilir**. Ezilen sürümde şunlar yapılır:

- Marka bağlantısı `core:panel` olur, KM logosu ve adı (`sistem_adi`) gösterilir.
- "Hesabım" bağlantısı `parola_degistir`'e, "Çıkış" KM'nin `logout` rotasına gider. "Kurum kullanıcıları", "Merkez"
  ve "Programım" bağlantıları kaldırılır ya da koşula bağlanır.
- `app.css` içindeki renk değişkenleri KM renklerine çekilebilir. Bu bir CSS katmanıdır, isteğe bağlıdır.

Bedeli: upstream `base.html` değişirse ezilen kopya elle güncellenir. Alternatif olarak upstream'e bu bağlantıları
ayarla değiştiren küçük bir ek önerilebilir. Tam Bootstrap uyumu ayrı ve büyük bir iş (2–4 gün); şu an önerilmez.

### 4.4 URL öneki

- Şablonlar ve JS adresleri `{% url %}` ya da `data-*` öznitelikleriyle üretiliyor. JS'de sabit `/okul/` veya `/api/`
  yolu bulunmadı (`static/timetable/*.js` tarandı). `location.pathname` ve `next`/`back` kullanımları göreli.
  `back` doğrulaması `startswith("/")` ile yapılıyor; önekle uyumlu.
- **Bir hata var:** `access._deny` JSON yanıtını `request.path.startswith("/api/")` koşuluyla seçiyor (`access.py:223`).
  `/ders-programi/api/...` altında bu koşul tutmaz ve 403 durumunda HTML döner; düzenleyicinin JS'i hata metnini
  gösteremez. Düzeltme: `"/api/" in request.path` ya da `request.resolver_match.url_name.startswith("api_")`.
- TT kök adrese (`""`) bağlanmamalı. TT'de `program/<pk>/` rotası var, KM'de de `program/` öneki var. Önerilen bağlama:
  `path("ders-programi/", include("timetable.urls"))`, `core.urls` satırından **önce**.
- TT testlerinden 5 dosya sabit yol kullanıyor (`"/program/"`, `"/giris/"`, `"/api/program/"`). Önek altında bunlar
  `reverse()` ile değiştirilmeli.

### 4.5 Giriş

TT'nin kendi giriş rotası var (`urls.py:11`, `timetable:login`). KM'de `LOGIN_URL = "login"` (`accounts.urls`) kalır.
`timetable:login` rotası köprü ara katmanında KM girişine yönlendirilir. Çıkışta `LOGOUT_REDIRECT_URL="login"` zaten
KM'ye gider. KM'nin `ForcePasswordChangeMiddleware`'i TT sayfalarında da çalışır; istenen davranış budur.

---

## 5. Veri köprüsü (TT → KM `program`)

### 5.1 Kavram eşlemesi

| TT | KM | Not |
|---|---|---|
| `Institution` | Karşılığı yok (tek kurum) | — |
| `School` (dönemlik program dosyası) | Bir `ProgramSurumu` dizisinin kaynağı | KM aynı anda tek geçerli sürüm tanır (`ProgramSurumuQuerySet.gecerli`) |
| `Timetable` (`active_timetable` = yayındaki) | `ProgramSurumu` (taslak → yayında → arşiv) | TT'de "yayınla" ile KM'de "yayınla" ayrı adımlar olarak kalmalı |
| `Period` | `DersSaati` | `period=index+1`, saat aralığı |
| `Subject` (`name`, `short`) | `Ders` (`kod=short`, `ad=name`) | `short` boşsa dışa aktarıcı `name[:4]` yazar. **TT'de `short` ders kodu (BİL103) olmalı** |
| `Teacher` (ad, soyad, unvan, bölüm, `tc_no`) | `ProgramOgretmeni` → `Personel` (`ad_soyad`, `personel_kodu` = TC) | KM ada göre eşler, TT'de TC var (§5.4) |
| `SchoolClass` | `Kisim` (`kod=short`) | `1SVN` biçimi; bölüm koddan bulunur |
| `Division`/`Group` | `Grup` (`bolunme`, `tum_kisim`) | — |
| `Classroom` | `Derslik` (`ad=name`) | `Building` aktarılmaz |
| `Lesson` | `HaftalikDers` | — |
| `Card` (gün, saat, uzunluk, derslik + ek derslikler) | `ProgramHucresi` (saat başına bir kayıt, tek derslik) | — |

### 5.2 TT'nin aSc XML çıktısı standart aSc 2012 XML'iyle uyumlu mu?

TT `asc_xml.export_school(school, timetable)` (`asc_xml.py:59-170`) ile KM'deki gerçek aSc dosyası
(`KAMYOSIS/aSc/asctt2012.xml`) ve KM içe aktarıcısının okuduğu alanlar karşılaştırıldı:

| Öğe/öznitelik | TT çıktısı | Gerçek aSc 2012 | KM `ice_aktar` okuyor mu? | Uyum |
|---|---|---|---|---|
| Kök `<timetable>` | `ascttversion="2026" importtype="database" options="idprefix:DP,daynumbering1"` | `importtype="database" options="export:idprefix:%CHRID,..."` | Yalnızca etiket adına bakıyor (`asc.py:156`) | ✔ |
| `periods/period@period,starttime,endtime` | `period="1"`, `"08:20"` | aynı | ✔ (`asc.py:225-228`) | ✔ |
| `daysdefs/daysdef@days` | `DALL` ve `D0..`, bit dizileri | aynı biçim | Okumuyor | ✔ |
| `weeksdefs`, `termsdefs` | maske başına bir tanım | aynı | Okumuyor | ⚠ §5.4 |
| `subjects/subject@id,name,short` | `S{pk}` | hex kimlik | ✔ `short` → kod | ✔ |
| `teachers/teacher@firstname,lastname,name,short` | `name="Ad Soyad"` | aynı sütunlar (+gender, email…) | ✔ önce `name` | ✔ |
| `classrooms/classroom@name,short,capacity,buildingid` | `capacity="*"` olabilir | aynı | ✔ `_kapasite("*")` → None | ✔ |
| `classes/class@name,short,classroomids,teacherid,grade` | ✔ | aynı | ✔ | ✔ |
| `groups/group@classid,name,entireclass,divisiontag,studentcount` | Her sınıfa `G{c}_0` "Tüm sınıf" (`entireclass="1"`), bölünmelere `divisiontag` sırası | aynı (+`studentids`) | ✔ (`asc.py:193-203`) | ✔ |
| `lessons/lesson@subjectid,classids,groupids,teacherids,classroomids,periodspercard,periodsperweek` | `periodsperweek="2.0"`, `groupids` tüm sınıf grubunu da içerir | aynı | ✔ tüm sınıf grupları atlanır (`asc.py:243`) | ✔ |
| `cards/card@lessonid,period,days,weeks,terms,classroomids` | Saat başına bir kart, `days="01000"` (0 tabanlı gün → dizi konumu), `locked` ek | aynı (`locked` yok) | ✔ `days` bitleri `start=1` → 1=Pazartesi (`asc.py:258-260`) | ✔ |

**Sonuç:** KM'nin `program/asc.py:ice_aktar()` fonksiyonu TT'nin XML çıktısını **doğrudan okuyabilir**. Yapı ve
öznitelik adları birebir uyumlu. Kalan uyumsuzluklar anlamsal (§5.4).

### 5.3 Süreç içi "KAMYOSİS'e gönder" köprüsü (taslak)

```python
# dersprogrami_kopru/yayin.py
import io
import xml.etree.ElementTree as ET
from django.db import transaction
from program.asc import ad_anahtari, ice_aktar
from program import eslestirme
from program.models import ProgramOgretmeni
from personel.models import Personel
from timetable.asc_xml import export_school

def kamyosise_gonder(timetable, kullanici):
    school = timetable.school
    if school.weeks_count > 1 or school.terms_count > 1:
        raise ValueError("A/B haftalı ya da dönemli program KAMYOSİS'e henüz aktarılamaz.")   # §5.4
    kok = ET.fromstring(export_school(school, timetable))
    tc_haritasi = kimlikleri_kalicilastir(kok, school)          # S12 → "DP-D:BİL103" … (aşağıda)
    veri = io.BytesIO(ET.tostring(kok, encoding="utf-8", xml_declaration=True))
    with transaction.atomic():
        surum, rapor = ice_aktar(veri, surum_adi=f"{school.name} – {timetable.name}",
                                 kaynak_dosya=f"dersprogrami:{timetable.pk}", kullanici=kullanici)
        # TC ile eşleme: adı tutmayan öğretmenler personele TC'den bağlanır
        for o in ProgramOgretmeni.objects.filter(haftalik_dersler__surum=surum,
                                                 durum=ProgramOgretmeni.BEKLIYOR).distinct():
            tc = tc_haritasi.get(o.asc_id)
            p = Personel.objects.filter(personel_kodu=tc).first() if tc else None
            if p is not None:
                eslestirme.eslestir(o, p)
    return surum, rapor
```

- **Arayüz:** KM'de `program:surumler` ekranına "Ders Programı modülünden al" düğmesi konur. Düğme köprüde bir sayfa
  açar: TT programları ve sürümleri listelenir, her satırda "Taslak olarak gönder" düğmesi bulunur. Yetki için
  `yetki_gerekli("ders-planlari", YONETIM)` istenir, çünkü KM'de sürüm yüklemek de bu yetkiyle yapılıyor
  (`program/views.py:110`). Ek olarak TT'de `yayin` yetkisi de aranabilir. Sonuç KM'nin mevcut akışına düşer:
  sürüm sayfası → öğretmen eşleştirme → başlangıç tarihiyle yayın. `takip` uygulaması etkilenmez, çünkü yeni sürüm
  yeni hücreler oluşturur ve eski `DersKaydi` kayıtları eski hücrelerde kalır (KM `docs/program_degisim_bicimi.md` §0).
- **Otomatik gönderim önerilmez.** TT'de "yayınla" işlemi (`views.py:355-375`) yalnızca `active_timetable` değerini
  değiştirir. KM'de yayın tarih ve sorumluluk gerektiren ayrı bir karardır (karar 5).

### 5.4 Uyumsuzluklar ve çözümleri

| # | Uyumsuzluk | Etki | Çözüm |
|---|---|---|---|
| U1 | **Öğretmen kimliği.** KM yalnızca normalize ada göre otomatik eşler (`asc.py:205-221`). TT'de `Teacher.tc_no` var, KM'de `Personel.personel_kodu` (TC). TT'de `title` ayrı tutulduğu için ad genelde temiz | Adı farklı yazılanlar "eşleştirme bekliyor" durumuna düşer | Köprü içe aktarmadan sonra TC ile eşler (yukarıdaki kod). **TC asla XML kimliğine yazılmamalı**, çünkü kimlik `asc_id` sütununda kalıcı olarak saklanır. KM değişim biçimi de TC gönderilmesini yasaklıyor (`docs/program_degisim_bicimi.md` §1). Bu yüzden eşleme haritası bellekte tutulur |
| U2 | **Kimlikler.** TT kimlikleri veritabanı numarasından üretiliyor (`S{pk}`, `T{pk}`, `C{pk}`, `R{pk}`). Kök öğedeki `idprefix:DP` seçeneğine rağmen kimliklere önek eklenmiyor. KM'de `asc_id` **genel olarak tekil** (`Ders`, `Kisim`, `Grup`, `Derslik`, `ProgramOgretmeni`). TT'de program kopyalanınca (yeni dönem) bütün pk'ler değişir | Her dönemde KM kayıtlarının `asc_id` değeri yeniden yazılır (`_bul_veya_yeni` önce kimliğe, sonra koda/ada bakıyor). TT'de bir dersin kısa kodu değiştirilirse `S12` eski `Ders` kaydını bulup kodunu yeni değere çevirmeye çalışır; yeni kod başka bir kayıtta varsa **IntegrityError** oluşur ve bütün aktarım geri alınır | Köprü kimlikleri iş anahtarına çevirir: ders `DP-D:<kod>`, kısım `DP-K:<kod>`, derslik `DP-R:<ad>`, grup `DP-G:<kısım>/<ad>`, öğretmen `DP-O:<ad_anahtari>`. Tüm başvurular (`classids`, `groupids`, `teacherids`, `classroomids`, `subjectid`, `classid`, `teacherid`) da yeniden yazılır. Ders kimlikleri `L{pk}` olarak kalabilir, çünkü `HaftalikDers.asc_id` tekil değil |
| U3 | **A/B haftası ve dönem maskesi.** `ice_aktar` `weeks` ve `terms` alanlarını yok sayıyor | İki haftada bir yapılan dersler KM'de her hafta görünür; ders takibi yanlış ders bekler | İlk aşamada köprü `weeks_count>1` ya da `terms_count>1` olan programı reddeder. Gerekirse sonra KM'ye hafta maskesi eklenir |
| U4 | **Ek derslikler.** TT kartında birden çok derslik olabiliyor (`card.room_ids`); KM yalnızca ilkini alıyor (`asc.py:256-257`) | Bilgi kaybı (küçük) | Kabul edilebilir ya da `ProgramHucresi` genişletilir |
| U5 | **Aynı adlı gruplar.** KM'de `Grup` kaydı `(kisim, ad)` çiftine göre tekil. TT'de bir sınıfın farklı bölünmelerinde aynı adlı gruplar olabilir | İki grup KM'de tek kayda birleşir | Köprü grup kimliğine bölünme numarasını katar ve uyarı verir; ya da TT'de grup adları tekil tutulur |
| U6 | **Aynı adlı iki öğretmen.** KM içe aktarıcısı ada göre ilk kaydı bulur | Birleşme (gerçek aSc dosyasında da aynı risk var) | U2'deki ad anahtarına TT pk'si eklenerek ayrıştırılır |
| U7 | **Birden çok eşzamanlı program.** TT'de `linked_programs` var (gündüz ve gece programı gibi). KM aynı anda tek geçerli sürüm kabul ediyor | Gece programı gönderilince gündüz programı geçersiz kalır | Karar 5: ya tek TT programı kullanılır ya da köprü birden çok TT programını tek XML'de birleştirir |
| U8 | Lesson tanımı üretimden sonra değiştirilmiş olabilir. Dışa aktarıcı dersleri `school.lessons` üzerinden, kartları `timetable` üzerinden alıyor | Kart sayısı ile `periodsperweek` tutmayabilir (KM bunu sarı uyarı sayar) | Göndermeden önce TT'nin doğrulayıcısı (`solver/validate.py`) çalıştırılıp sonuç gösterilir |

### 5.5 KM'nin JSON değişim biçimi hakkında

KM'de `docs/program_degisim_bicimi.md` belgesi bir "kamyosis-program" JSON biçimi tanımlıyor; ancak **bunu okuyan kod
henüz yok** (depoda `kamyosis-program` geçmiyor). Biçim, ayrı servis senaryosu (Seçenek B) için tasarlanmış. Süreç
içi bütünleşmede aSc XML yolu bugün çalışan kodla yapılabildiği için **ilk aşamada XML önerilir**. JSON okuyucusu
yazılırsa da yukarıdaki U1–U8 aynen geçerlidir.

---

## 6. KM ile örtüşen alanlar

| TT özelliği | KM karşılığı | Aynı kavram mı? | Öneri |
|---|---|---|---|
| **Nöbet** (`duty.py`, `DutyPlace`/`Duty`): bir nöbet yeri için **haftanın her günü** N öğretmen. CP-SAT ile dağıtılır, dersi olan gün tercih edilir, haftalık üst sınır var (`duty.py:1-10`, `models.py:1207-1243`) | `nobet`: **aylık** nöbet görevleri (EK-3), rütbe uygunluğu, yatılı görev, nöbet yılı boyunca adalet, kısıtlamalar ve puantaj (`nobet/models.py`) | **Hayır.** TT'deki okul içi teneffüs nöbeti, KM'deki ise askeri/idari aylık görev | **KM'ninki kalsın.** TT nöbet rotaları (`duties`, `duties_print`) ve menü öğesi kapatılır. Okulda ayrıca teneffüs nöbeti tutuluyorsa ileride açılabilir (karar 4) |
| **Vekâlet** (`Absence`/`Substitution`, `substitutes.py`): tarihli devamsızlık ve saat başına vekil önerisi (aynı branş, o sınıfa giren, boşta olan), e-posta, girişsiz koridor ekranı | `takip.DevirTalebi`: tarihli `DersKaydi` için devralacak personel, talep → onay → kesinleşme akışı. Ek ders hesabının dayanağı | **Kısmen.** Amaç ortak (dersi başkası yapar). KM'deki **resmi ve onaylı kayıt**, TT'deki **planlama ve öneri** aracı | **KM'ninki kalsın** (ek ders ve onay akışı nedeniyle). TT vekâlet ekranı ilk aşamada kapatılır. Sonra **köprü:** KM `devir_yeni` ekranında TT'nin `substitutes.py` öneri sıralaması "önerilen vekiller" olarak gösterilir (TT Teacher ↔ Personel eşlemesiyle). İki ayrı vekâlet kaydı tutulmamalı |
| **Etkinlik ve telafi** (`events.py`, `Event`) | Yok | — | **TT'ninki kalsın**, ancak telafi dersi ek ders hesabını etkiler. İleride takip'e bağlanması değerlendirilmeli |
| **Sınav programı** (`exam*.py`): dönem, sınav üretimi, birleştirme/bölme, CP-SAT ile oturum, salon (kapasite) ve gözetmen ataması, gözetmen müsaitliği, yazdırma ve Excel | Yok. `sinav-planlari` birimi "sırada" (PPYS SPS/SMS/STS: oturum, salon, öğrenci yerleşimi, gözetmen, mazeret, sınav görevine katılım) | KM'de boş alan | **TT'ninki kalsın**, `sinav-planlari` birimine bağlanır (§3.6). Birimin `modul_url` alanı parametresiz olmalı; köprüde "etkin programın sınavlarına" yönlendiren küçük bir görünüm yazılır. Eksikler: öğrenci bazlı yerleşim ve sınav mazeretleri TT'de sınırlı. PPYS karşılaştırması ayrı yapılmalı |
| **Öğretmen hesapları** (`teacher_accounts.py`): toplu hesap açma, geçici parola, e-postayla parola bağlantısı, "parolamı unuttum" | KM: kullanıcılar yönetim panelinden ya da Access aktarımıyla açılır; `parola_degismeli` var; `User.personel` bağlantısı var; bölüm hesapları ağırlıkta | Çakışıyor | **KM'ninki kalsın.** `teacher_accounts`, `password_*`, `institution_users`, `school_users` kapatılır. **Köprü:** `Teacher.user` alanı, `User.personel.personel_kodu == Teacher.tc_no` eşleşmesiyle otomatik doldurulur. Böylece kişisel hesabı olan öğretim elemanı TT'deki "Programım" ve "İsteklerim" ekranlarını kullanabilir (karar 4) |
| **Öğretmen istekleri ve izin** (`teacher_requests.py`, `LeaveRequest`, `AvailabilityRequest`) | `nobet.NobetKisitlamasi` (izin, tayin…; nöbet içindir) | Kısmen | **TT'ninki kalsın** (müsaitlik programın girdisi). İleride TT izni KM nöbet kısıtlamasına aktarılabilir |
| **Bölümler** (`departments.py`): bölüm sorumlusunun öneri ve onay akışı | `personel.Bolum`, kapsamı `bolum` olan yetkiler | Tamamlayıcı | **Köprü:** her TT programında `Department` kayıtları KM `Bolum` ile ad ya da kod üzerinden eşlenir. `Department.users` kapsamı `bolum` olan Düzenleme/Yönetim kullanıcılarıyla eşitlenir (§3.4) |
| **Web yayını, .ics takvim** (`public.py`, `teacher_ics`): girişsiz ve gizli bağlantılı sayfalar | Yok | — | Kurum güvenlik politikası kararı (karar 4). **Varsayılan: kapalı** |
| **E-posta bildirimleri** (`notify.py`) | Yok | — | KM'de `EMAIL_HOST` boş olduğu için kendiliğinden kapalı. Uygulama içi bildirim (`Notification`) çalışır |
| **ÜYBS aktarımı** (`uybs.py`) | Yok | — | **TT'ninki kalsın** |
| **Teacher ↔ Personel** (ad, unvan, bölüm, TC) | `personel.Personel` | Veri tekrarı | Kısa vadede TC ile eşleme. Uzun vadede `Teacher.personel` FK alanı eklenip ad, unvan ve bölüm KM'den okunabilir (upstream değişikliği gerektirir) |

---

## 7. Bütünleşik kurulumda kapatılması gerekenler

| Parça | Ne yapar | Risk | Nasıl kapatılır |
|---|---|---|---|
| `updater.py` + rota `system_update` (`urls.py:24`) | KM kökünde `git fetch/pull/reset --hard`, ardından `os._exit(3)` | **K4**: kod ve sunucu | Köprü ara katmanında 404 + menüden kaldırma (sayfa merkez panelinde) |
| `backup.py` + rota `backups` (`urls.py:23`) | `create`: **bütün** veritabanının dökümü. `restore`: **`flush`** + `loaddata` | **K2**: bütün KM verisi gider | 404. `AUTO_BACKUP = False` (`services.py:108-109` üretim öncesinde yedek alıyor). KM kendi yedeğini almaya devam eder |
| `backup.compare` + rota `backup_compare` (`urls.py:53`) | Alt süreçte `migrate` + `loaddata` (`DJANGO_DB_PATH`) | **K3**: canlı veritabanına yükleme | 404. `tests/test_backup_compare.py` KM'de **koşturulmamalı** (silinmeli ya da atlanmalı) |
| `create_demo`, `import_asc` (yeni kurum), `central_school_new`, `school_create` | Yeni kurum ve kullanıcı açar | Tek kurum ilkesini bozar | 404. Program ekleme kurum sayfasındaki `program_new`/`program_import` ile yapılır |
| `institution_users`, `school_users`, `teacher_accounts`, `password_set*`, `password_forgot*` | Hesap ve yetki yönetimi | Yetki eşitlemesini ezer, parola politikasını atlar | 404 |
| `login`, `account` | TT giriş sayfası ve hesap sayfası | Giriş akışının ikiye bölünmesi | Yönlendirme: `login` → KM `login`, `account` → `parola_degistir` |
| `public_*`, `publish_settings`, `teacher_ics` | Girişsiz sayfalar | Kurum içi bilginin dışarı açılması | Karar 4. Varsayılan 404 |
| `duties`, `duties_print` (ve gerekirse `substitutions`) | §6 | Kafa karışıklığı | Karar 4 |
| `management/commands/sunucu.py`, `yedekle.py` | Bağımsız sunucu ve yedek | Yanlışlıkla çalıştırılması | Kullanılmaz. Belgelenir |
| `baslat.py`, `config/`, `.bat`/`.sh`, `Dockerfile`, `Caddyfile`, `paket/` | Bağımsız kurulum | — | **Kopyalanmaz.** Yalnızca `timetable/` alınır |

**Kapatma mekanizması (önerilen):**

1. **Köprü ara katmanı** (`dersprogrami_kopru.middleware.KopruMiddleware`, `SchoolAccessMiddleware`'den önce):
   `resolver_match.namespace == "timetable"` ve `url_name in settings.TIMETABLE_DISABLED_ROUTES` ise `Http404` verir.
   Yönlendirme ve sınav kapısı (§3.6) da burada yapılır. TT koduna dokunmaz. Süper kullanıcı için de geçerlidir;
   özellikle K2–K4 için bu şart.
2. **Menü:** `templatetags/navigation.py` içindeki `NAV_GROUPS` modül düzeyinde bir liste. URL üreticileri lambda
   olduğu için rota adı dışarıdan okunamıyor. İki yol var:
   - **(a) Önerilen:** upstream'e küçük bir ek. Her öğeye rota adı eklenir ya da `build()` içinde
     `getattr(settings, "TIMETABLE_DISABLED_ROUTES", ())` denetlenir. Aynı ayar `access.process_view` içinde de 404
     için kullanılabilir.
   - **(b)** Köprünün `AppConfig.ready()` metodunda `NAV_GROUPS` öğeleri etiketlerine göre süzülür. Kırılgandır.
3. **base.html** bağlantıları: §4.3'teki ezme ile.
4. **Merkez paneli** (`central.html`) içindeki güncelleme ve yedek bağlantıları da gizlenmeli. Şablon ezilir ya da
   `central` rotası da kapatılır (karar 4; merkez günlüğü `central_log` açık kalabilir).

---

## 8. Riskler

| Risk | Ayrıntı | Önlem |
|---|---|---|
| **Migration'lar** | 46 dosya (0001–0045). Veri migration'ları `0004`, `0008`, `0013`, `0024`, `0043` yalnızca TT tablolarına dokunuyor, boş veritabanında iş yapmıyor. Tablo önekleri `timetable_*`, KM'yle çakışma yok. `0013_institutions` mevcut okullara kurum açıyor; KM'de boş başlandığı için etkisiz | İlk `migrate` işlemi **kopya veritabanında** (`KAMYOSIS_DB=...`) denenir. KM `yayinla.py` her açılışta `migrate` çalıştırdığı için (`yayinla.py:50`) sıralama dikkatli yapılmalı |
| **Çok kurumlu varsayımlar** | `School.save()` kurum yoksa yeni kurum açar. `import_asc` ve `central_school_new` yeni kurum açar. Bildirim yöneticileri ve hesap listeleri `Membership` sorgular | Tek kurum + eşitleme (§3) + ilgili rotaları kapatma (§7) |
| **Web sürecinde iş parçacıkları (waitress)** | KM tek süreçte `threads=8` ile çalışıyor (`yayinla.py:61`). `thread` kipinde CP-SAT (8+ iş parçacığı, dakikalarca, sıkı modda ceza düşürme 600 sn'ye kadar) CPU'yu doldurur; KM sayfaları yavaşlar. Sunucu yeniden başlarsa iş yarım kalır. Sınav çözümü her zaman web sürecinde çalışır | `TIMETABLE_JOB_BACKEND="worker"` ve ayrı `manage.py calisan` süreci (karar 3). `SOLVER_WORKERS` değeri çekirdek sayısının 1–2 altına çekilir (4 çekirdekte 2–3). `arkaplanda_baslat.bat` ve `durdur.bat` iki süreci birlikte yönetecek şekilde güncellenir |
| **SQLite eşzamanlılığı** | KM'de `OPTIONS` yok: varsayılan 5 sn bekleme, `DEFERRED` işlem, WAL kapalı. TT çalışan süreci her 2 sn'de nabız ve ilerleme yazıyor (`jobs.py:124-135`), üretim sonucu toplu yazılıyor. İki süreç ve 8 web iş parçacığı birlikte çalışınca "database is locked" hataları beklenir | TT'nin ayarları KM'ye alınır: `timeout=20`, `transaction_mode="IMMEDIATE"`, `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=20000`. **Yan etki:** WAL açıkken `db.sqlite3` dosyasını kopyalayarak alınan yedek (`db_yedek_*.sqlite3`) eksik kalabilir. Yedek `sqlite3` backup API'siyle ya da `VACUUM INTO` ile alınmalı |
| **ortools: Windows ve Python 3.13** | TT belgeye göre Python 3.13 + Windows/waitress üzerinde üretimde çalışıyor. Bu, `ortools>=9.12` için cp313-win_amd64 tekerleğinin kullanılabildiğini gösteriyor. 64 bit Python şart. Bağımlılıklarla ~150–200 MB. Kurum ağı kapalıysa internetten kurulum yapılamaz | KM `.venv` içine kurulum ayrı bir adımda doğrulanır. Gerekirse TT'nin `paket/` yaklaşımıyla `wheelhouse` hazırlanır. Sürümler sabitlenir (`ortools==…`, `protobuf==…`) |
| **Test süresi ve yan etkileri** | 74 dosyada 544 test fonksiyonu var, `--parallel 1` ile 8–10 dk sürüyor. 64 dosya `User` içe aktarıyor, 5 dosyada sabit yol var. `test_backup_compare` **K3'ü tetikler**. `test_system_update` ile yedek testleri kapatılan rotalar yüzünden düşer | Faz 4. KM'de `manage.py test timetable --parallel 1` ayrı bir hedef olur. Kapatılan özelliklerin testleri `skipIf(settings.TIMETABLE_DISABLED_ROUTES…)` ile atlanır ya da silinir |
| **Dosyaya yazan kod** | `backup.py` (`BACKUP_DIR` içine dökümler, karşılaştırma JSON'u, geçici `.sqlite3`), `updater.py` (`BASE_DIR` içine `guncelleme-*.json`), `sunucu.py` (`takilma.log`). Basılı çıktı logosu dosyaya değil veritabanına data URI olarak yazılıyor (`printing.py`) | Tümü kapatılan parçalarda. `BACKUP_DIR` yine de tanımlanmalı (`kayitlar/` altında, git dışı) |
| **Kişisel veri** | TT `Teacher.tc_no` ve `email` alanları KM'de ikinci bir TC kopyası oluşturur. KM değişim biçimi TC aktarımını yasaklıyor | TC yalnızca eşleme için bellekte kullanılır, XML kimliğine yazılmaz (§5.4 U1). Uzun vadede `Teacher` → `Personel` FK |
| **403 JSON hatası (önek)** | `access.py:223` | §4.4'teki küçük düzeltme |
| **Her istekte bağlam işlemcisi** | `timetable.access.can` KM sayfalarında da 2 sorgu çalıştırır | Önemsiz. İstenirse ad alanına göre sınırlandırılır |
| **Upstream ile ayrışma** | `gen2.py` ayrı bir çalışmada (Codex) gelişiyor. KM'ye kopyalanan modüle yapılan her yama birleştirme maliyeti doğurur | Yamaları küçük ve ayarla açılıp kapanan tutmak, mümkünse upstream'e göndermek (karar 1) |

---

## 9. Önerilen adım adım plan

Her faz ayrı bir dalda yapılır, sonunda KM'nin kendi testleri (`manage.py test accounts core personel program takip nobet`)
ve fazın kabul ölçütü çalıştırılır. Bütün denemeler **gerçek verinin kopyasında** (`KAMYOSIS_DB`) yapılır.

| Faz | İş | Kabul ölçütü | Efor |
|---|---|---|---|
| **0. Kararlar ve ortam** | Aşağıdaki 5 karar. KM `.venv` için `ortools`, `reportlab`, `segno`, `tzdata` kurulumunun kopya ortamda denenmesi | `python -c "import ortools"` KM venv'inde çalışıyor | 0,5 gün |
| **1. Kodu alma, kullanıcı modeli, ayarlar** | `timetable/` KM'ye alınır (karar 1). 19 alan ve 5 içe aktarma düzeltilir (§2). `INSTALLED_APPS`, ara katmanlar (`LoginRequiredMiddleware` + `SchoolAccessMiddleware`), `builtins`, bağlam işlemcisi, `TIMETABLE_*`, `AUTO_BACKUP=False`, `BACKUP_DIR`, `PUBLIC_URL=""`, SQLite `OPTIONS`. URL `ders-programi/` | `manage.py check` temiz. `makemigrations --check` değişiklik yok. Kopya DB'de `migrate` başarılı. Girişsiz `/ders-programi/` istekleri KM girişine yönleniyor. Süper kullanıcı örnek bir program açıp üretebiliyor | 1–1,5 gün |
| **2. Güvenlik kapatmaları ve kabuk** | `dersprogrami_kopru` uygulaması: `KopruMiddleware` (`TIMETABLE_DISABLED_ROUTES` → 404, `login`/`account` yönlendirmesi). `access._deny` önek düzeltmesi. Menü süzme (§7). `templates/timetable/base.html` ezilir (marka, çıkış, parola). Merkez panelindeki bağlantılar gizlenir | K2–K4 rotaları süper kullanıcıya da 404 veriyor (test). `/ders-programi/api/...` 403 yanıtı JSON dönüyor. Menüde kapatılan öğe yok | 1 gün |
| **3. Yetki köprüsü** | Veri migration'ı: tek `Institution` ve `ders-programi` birimi (+ isteğe bağlı yetki kopyası). `esitle()` + sinyaller + `ders_programi_yetki_esitle` komutu. Sınav kapısı ve `timetable_extra_perms` eki (§3.6). KM kısayollarına (`core/context_processors.py:_kisayollar`) bağlantı | Birim testleri: Görüntüleme/Düzenleme/Yönetim kullanıcıları ilgili TT işlemlerini yapabiliyor ve yapamıyor. Yetki silinince erişim kalkıyor. Kapsamı `bolum` olan kullanıcı yalnızca görüntülüyor | 1,5 gün |
| **4. TT test paketi KM'de** | 64 dosyada `get_user_model()`, 5 dosyada `reverse()`. Kapatılan özelliklerin testleri atlanır. **`test_backup_compare` kaldırılır** | `manage.py test timetable --parallel 1` yeşil (yaklaşık 10 dk) | 1–1,5 gün |
| **5. "KAMYOSİS'e gönder" köprüsü** | `kamyosise_gonder()` (§5.3): kimlik kalıcılaştırma (U2), TC ile eşleme (U1), hafta/dönem reddi (U3), gönderim öncesi doğrulama (U8). KM `program:surumler` ekranına düğme | Test: örnek TT programı gönderilince beklenen sayıda `HaftalikDers` ve `ProgramHucresi` oluşuyor. Aynı program iki kez gönderilince `Ders`/`Kisim`/`Derslik` kayıtları çoğalmıyor. TC ile eşleşen öğretmen "elle eşleştirildi" durumuna geçiyor. Mevcut takip kayıtları bozulmuyor | 2 gün |
| **6. Gerçek veriyle ilk tur ve dağıtım** | KM'deki gerçek aSc XML'i (`aSc/asctt2012.xml`) TT'ye `program_import` ile alınır. TC'ler TT ÜYBS ekranından ya da köprüyle Personel'den doldurulur. Gerçek veriyle üretim denenir. Çalışan süreci (`calisan`) için `.bat` ve otomatik başlatma, `durdur.bat` güncellemesi, WAL uyumlu yedek | Kopya DB'de gerçek programla üretim tamamlanıyor, KM sayfaları üretim sırasında yanıt veriyor. TT → KM gönderimi gerçek veride sarı uyarı dışında hatasız | 1–1,5 gün |
| **7. (İsteğe bağlı) Örtüşme köprüleri** | `Teacher.user` ↔ `User.personel` otomatik bağlama. `Department` ↔ `Bolum` eşitleme. KM devir ekranına TT vekil önerisi. `sinav-planlari` için yönlendirme görünümü | Her biri ayrı testli | 2–4 gün |
| **8. (İsteğe bağlı) Görsel uyum** | `app.css` değişkenlerini KM renklerine çekmek ya da tam Bootstrap uyarlaması | Görsel kontrol | 1–3 gün |

**Çekirdek toplam (Faz 0–6):** yaklaşık 8,5–11 iş günü. İsteğe bağlı fazlarla 11,5–18 gün.

### İnsanın vermesi gereken kararlar

1. **Kodun alınma biçimi:** `timetable/` KM'ye **kopya** olarak mı alınacak, yoksa upstream'den güncelleme çekebilmek için
   **git subtree / alt modül** olarak mı? `gen2.py` ayrı bir çalışmada (Codex) gelişmeye devam ediyor, bu yüzden
   subtree ve yamaları upstream'e ayar bayrağı olarak geri göndermek öneriliyor. Bu karar, §2 ve §7'deki yamaların
   nereye yapılacağını belirler.
2. **Yetki birimi ve seviye eşlemesi:** TT için yeni bir `ders-programi` birimi mi açılacak (önerilen), yoksa mevcut
   `ders-planlari` yetkisi mi kullanılacak? Mevcut DPS/DMS yöneticilerinin yetkileri kopyalansın mı? §3.4 tablosu
   (özellikle Düzenleme = `veri`+`vekalet` ve kapsamı `bolum` olanlar = yalnız görüntüleme + bölüm portalı) uygun mu?
   Sınav ayrı birimden (`sinav-planlari`) mi yetkilendirilsin?
3. **Arka plan çalışma kipi:** `worker` (ayrı `calisan` süreci; önerilen, ama ikinci bir süreç yönetmek gerekir) mı,
   yoksa `thread` (tek süreç; basit, ama üretim sırasında KM yavaşlar) mı? Çözücüye kaç çekirdek ayrılacak
   (`SOLVER_WORKERS`)?
4. **Örtüşen ve dışa açık özellikler:** TT'de nöbet ve vekâlet kapatılsın mı (önerilen: KM `nobet` ve `takip`
   esas kalsın)? Sınav modülü `sinav-planlari` olarak açılsın mı? Öğretim elemanları kişisel hesapla TT'deki
   "Programım" ve "İsteklerim" ekranlarını kullanacak mı (`Teacher.user` ↔ `User.personel`)? Girişsiz web yayını
   ve .ics takvim kurum politikasına uygun mu (önerilen: kapalı)?
5. **KAMYOSİS'e yayın akışı:** TT'den KM'ye gönderim elle mi yapılsın ("taslak olarak gönder" düğmesi, yayın KM'de
   tarihle; önerilen), yoksa TT'de yayınlanınca otomatik mi? Aynı anda birden çok TT programı (gündüz/gece,
   `linked_programs`) kullanılacaksa KM'ye tek sürümde birleştirilerek mi gönderilsin? A/B haftası kullanılacak mı?
   Kullanılacaksa KM'ye hafta maskesi eklenmesi gerekir.
