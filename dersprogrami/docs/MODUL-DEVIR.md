# Ders Programı modülü — devir belgesi

> Bu belge, modülü devralan geliştiricinin (ve onun Claude'unun) projeyi baştan keşfetmek zorunda
> kalmaması için yazıldı. Önce bunu, sonra [../CLAUDE.md](../CLAUDE.md) (çalışma kuralları) ve
> [../README.md](../README.md) (ekranlar, kavramlar, kısıt listesi) okunmalı.
>
> Yazıldığı tarih: 2 Kasım 2026 (modül yapısıyla güncellendi) · Dal: `claude/elegant-fermi-mtxjbt`

## 1. Modül ne yapar

Okul ve meslek yüksekokulları için **otomatik ders programı** üretir ve programın yıl boyunca kullanımını
yönetir. aSc TimeTables mantığını örnek alır (tasarım gerekçesi: [`../../docs/asc-timetables-analizi.md`](../../docs/asc-timetables-analizi.md)).

- **Veri girişi:** program (dönem), ders saatleri, sınıf/kısım, bölünme ve gruplar, öğretmen, derslik, bina,
  ders, müsaitlik ızgaraları, kart ilişkileri (aSc'deki kuralların çoğu), seçmeli ders ve öğrenci seçimleri.
  Excel ve aSc XML ile içe/dışa aktarım, kurulum sihirbazı, bölüm sorumlularının veri önerisi.
- **Üretim:** OR-Tools CP-SAT ile kesin kurallara uyan, cezası en düşük program; çözülemiyorsa hangi
  kuralların birlikte sağlanamadığının açıklaması.
- **Üretim sonrası:** sürükle-bırak düzenleme, ihlal onarımı, ceza düşürme, çözüm merkezi, kalite karnesi,
  sürümler, karşılaştırma, raporlar / PDF / Excel.
- **Günlük işler:** vekâlet, etkinlik ve telafi dersi, derslik ayırma, nöbet, öğretmen
  istekleri, öğretmen hesapları (Programım, telefon takvimi), web yayını, e-posta bildirimleri, ÜYBS aktarımı.
- **Çok kurumlu:** tek kurulumda birden çok kurum, kurum düzeyinde yetkiler.
- **Modüller:** ana sayfada **Ders Planlama** (yukarıdakilerin hepsi) ve **Sınav Planlama** (vize/final/bütünleme
  programı, salon ve gözetmen ataması) ayrı kartlardır; yeni modül eklenebilir (§3.1). Kullanıcı modüllerle
  sınırlanabilir (ör. yalnızca Sınav Planlama).

Durum: üretimde kullanılıyor (bir MYO'nun ~1100 kartlık programı). 560 otomatik test var, hepsi geçiyor.

## 2. Teknoloji

| Katman | Ne kullanılıyor |
|---|---|
| Dil / çatı | Python 3.13, Django 5.2 (uygulamalar: `timetable` = Ders Planlama + ortak veri, `sinav` = Sınav Planlama) |
| Çözücü | OR-Tools CP-SAT (`ortools>=9.12`) |
| Veritabanı | SQLite (yerel) ya da PostgreSQL (`DATABASE_URL`) |
| Arayüz | Sunucu tarafı Django şablonları + sade JavaScript (`timetable/static/timetable/*.js`). Derleme adımı, npm, harici CDN **yok** |
| Dosya | openpyxl (Excel), reportlab (PDF), segno (QR) |
| Yayın | gunicorn (Linux) / waitress (Windows), whitenoise, Docker + Caddy ([../YAYIN.md](../YAYIN.md)) |

`config/` yalnızca bu bağımsız kurulumun Django projesidir; asıl kod `timetable/` ve `sinav/` klasörleridir.

## 3. Klasör haritası

```
dersprogrami/
  config/               bağımsız kurulumun settings / urls / wsgi
  baslat.py             yerel başlatıcı (git pull → migrate → sunucu; kendini güncelleme)
  timetable/
    models.py           ana veri modeli (aşağıda)
    modules.py          modül kaydı: ana sayfa kartları, açık modül, modül bazlı erişim
    access.py           TEK yetki noktası: SchoolAccessMiddleware + URL adı → yetki tabloları + denetim günlüğü
    urls.py             134 URL, ad alanı "timetable"
    views.py            ana sayfalar ve JSON API        data_views.py    veri giriş listeleri/formları
    solver/             Django'dan BAĞIMSIZ çözücü katmanı
      problem.py          sade problem yapısı, öğrenci atomları
      builder.py          veritabanı → Problem
      feasibility.py      üretim öncesi veri denetimi
      cpsat.py            CP-SAT modeli (_Builder), solve(), minimal_repair(), explain()
      dayrepair.py        gün komşuluğu onarımı (2–3 günün kartlarını birlikte yeniden dizer)
      penaltyrepair.py    kesin program bulunduktan sonra ceza düşürme (gün komşuluğu)
      relations_extra.py  kart ilişkisi türlerinin kısıtları
      validate.py         çözücüden bağımsız doğrulayıcı (elle düzenlenmiş program için de)
      gen2.py, blocks.py  Gen2 / Gen3 deneysel üreticiler (menüden gizli, bkz. §6)
    services.py         üretimi başlatma, sonucu yazma, ihlal çözme, ceza düşürme
    jobs.py             üretim işleri (thread ya da worker kipi)
    school_improve.py   ImproveJob kuyruğu: okul geneli iyileştirme
    quick_jobs.py       aynı kuyrukta "İhlalleri çöz" ve "Cezayı düşür" işleri
    resolve.py          çözüm merkezi (en az kart oynatan öneriler)
    editing.py, grid.py ana görünüm: hücre uygunluğu, taşıma, ızgara verisi
    penalty.py, quality.py, pending.py   ceza dökümü, kalite karnesi, bekleyenlerin nedenleri
    substitutes.py      vekâlet önerileri            events.py      etkinlik, telafi, derslik ayırma
    duty.py             nöbet
    students.py         öğrenciler, seçmeliler, şube planı
    teacher_accounts.py, teacher_calendar.py, teacher_requests.py   öğretmen hesabı tarafı
    departments.py      bölüm sorumlularının veri önerisi
    public.py           giriş gerektirmeyen web yayını (gizli bağlantı)
    asc_xml.py, excel.py, importer.py, report_*.py, printing.py     içe/dışa aktarım ve çıktılar
    uybs.py, refs.py    ÜYBS (üniversite bilgi sistemi) aktarımı
    notify.py, notifications.py    e-posta ve uygulama içi bildirimler
    versions.py         sürümler (her yazma işlemi geri alınabilir)
    backup.py, updater.py          yedek ve kendini güncelleme (bağımsız kurulum içindir)
    management/commands/ calisan (iş kuyruğu çalışanı), generate_timetable, seed_demo, yedekle, sunucu
    templatetags/navigation.py     sol menü tanımı
    tests/              72 test dosyası
  sinav/                Sınav Planlama modülü (ortak veriyi timetable'dan kullanır)
    module.py           modül kaydı: başlık, sol menü, yetki tablosu, işlem günlüğü adları
    models.py           ExamPeriod, Exam, ExamPlacement, ExamRoom (tablo adları eskisi gibi timetable_exam*)
    services.py         derslerden sınav üretme, birleştirme, gözetmen müsaitliği, arka plan çözümü
    solver.py           sınav yerleştirme CP-SAT modeli
    views.py, urls.py   sayfalar (adres öneki /sinav-planlama/, ad alanı "sinav"), excel.py çıktı
    tests/              sınav ve modül testleri
```

### 3.1 Modül yapısı

- `timetable/modules.py` kayıt defteridir. Her modül `Module(key, title, description, icon, namespace, landing,
  entry, nav_groups, routes, open_routes, labels)` ile kendini `AppConfig.ready()`'de kaydeder (örnek:
  `sinav/apps.py`, `sinav/module.py`; Ders Planlama `timetable/apps.py`'de kaydolur).
- Ana sayfa (`/`) kullanıcının açabildiği modülleri ve her birindeki programları gösterir. Ders Planlama'nın giriş
  sayfası `/ders-planlama/` (Kurumlarım), Sınav Planlama'nınki `/sinav-planlama/`.
- Kenar çubuğunda ve üst şeritte modül değiştirici vardır; menü açık modülün `nav_groups`'udur.
- **Ortak veri sayfaları** (`access.SHARED_ROUTES`: sınıf, öğretmen, derslik, ders, program ayarları ...) her
  modülden açılır ve en son girilen modülün menüsüyle görünür (oturumda `modul`).
- **Erişim:** `Membership.modules` boşsa kullanıcı bütün modülleri görür; doluysa yalnızca onları. Modül içindeki
  işlemler yine kurum yetkileriyle denetlenir (Sınav Planlama: görüntüleme ile bakılır, veri girişi ile değiştirilir).
  Kullanıcılar sayfasında modül kutuları vardır; modülü kısıtlı yönetici yalnızca kendi modüllerini verebilir.
- Eski sınav adresleri (`/okul/<pk>/sinavlar/...`) yeni adreslere yönlendirilir.

## 4. Veri modeli

```
Institution (kurum)
 └─ School  = bir "program dosyası" (ör. 2026/27 1.YY). Tarihsel adı School; arayüzde "program".
     ├─ Period (ders saati), Building, Classroom (kapasite), Subject (ders adı)
     ├─ Teacher (sınırlar, branş, tc_no, isteğe bağlı user → öğretmen hesabı)
     ├─ SchoolClass (sınıf/kısım, mevcut) └─ Division (bölünme) └─ Group
     ├─ Lesson (ders adı + sınıflar/gruplar + öğretmenler + derslikler + haftalık saat + kart uzunluğu)
     ├─ Availability (öğretmen/sınıf/derslik/ders için gün×saat: yasak / koşullu)
     ├─ CardRelationship (kart ilişkileri: aSc'deki kurallar, önemi kesin ya da ceza)
     ├─ Student (seçmeliler için)
     ├─ Timetable (üretilmiş sürüm; active_timetable = yayındaki)
     │    ├─ Card (lesson, day, period, length, classroom, extra_rooms, locked)
     │    ├─ TimetableVersion (geri alınabilir anlık görüntüler)
     │    └─ ImproveJob (kind: school / resolve / penalty)
     ├─ Absence, Substitution (vekâlet), Event (etkinlik / telafi / derslik ayırma)
     ├─ DutyPlace, Duty (nöbet)
     ├─ [sinav] ExamPeriod → Exam (ders adı, sınıflar, dersler) → ExamPlacement → ExamRoom (salon, gözetmenler)
     └─ LeaveRequest, AvailabilityRequest, Department, DepartmentSubmission (istek ve onay akışları)
Membership (user × institution × yetkiler [+ program kısıtı] [+ modül kısıtı]) · AuditLog · Notification · ReportPreset
```

- **Kart** = dersin tek oturumu. 6 saat / uzunluk 2 → 3 kart.
- **Öğrenci atomu:** sınıf, bölünmelerinin gruplarının kartezyen çarpımı kadar atoma ayrılır; iki ders ancak
  atom kümeleri kesişirse çakışır. Bölünme kuralları tek genel kurala iner (`solver/problem.py`).
- **Hafta / dönem maskesi:** A/B haftası ve dönemlik dersler; kartlar yalnızca ortak hafta-dönemde çakışır.
- Kullanıcı modeli: modeller `"auth.User"` adını doğrudan kullanır (19 yer); migration'lar `AUTH_USER_MODEL` ile.

## 5. Çözücü — nasıl çalışır

**Değişkenler** (`cpsat.py`): `x[k,d,p]` kart k, gün d, saat p'de başlar; `y[k,r]` kart k, derslik r'de.

**Katı mod (STRICT, önerilen):** her kart yerleşir; öğretmen / öğrenci atomu / derslik çakışmaz; günlük ve
haftalık sınırlar, müsaitlik yasakları, "kesin" kart ilişkileri sert kısıttır. Amaç = ceza toplamı:

| Ağırlık | Ceza |
|---|---|
| 300 / 60 / 15 | önemi yüksek / normal / düşük kart ilişkisi |
| 100 | sınıf boşluğu · 50 güne geç başlama · 10 öğretmen boşluğu · 5 koşullu hücre |

**Gevşek mod (RELAXED):** kaynak çakışmaları yine sert; diğer kurallar 1000 cezalı, yerleşmeyen kart 10000
cezalı olur. Çözülemeyen veride bile "en yakın taslak + kırılan kurallar" verir.

**Katı üretimin akışı (otomatik süre, büyük programlar):**
1. Gevşek taslak → ihlal komşuluğunu serbest bırakan onarım turları (`_repair_search`, `REPAIR_UNTIL`).
2. Kesin program bulununca **ceza düşürme** (`penaltyrepair.PenaltyRepair`, en çok 600 sn, 120 sn düşmezse
   durur): rastgele 2–3 günün kartları serbest, diğerleri sabit; toplam ihlal artamaz.
3. Sonuç bağımsız doğrulayıcıdan (`validate.py`) geçmeden programa yazılmaz.

**Program sonrası düğmeler** (ana görünüm, `quick_jobs.py`, arka plan işi + ilerleme + "Durdur"):
- *İhlalleri çöz* (40 / 90 sn az değişiklik → 600 / 1800 sn gün komşuluğu, `services.resolve_search`).
- *Cezayı düşür* (60 / 300 / 900 sn, `services.penalty_search`). Kesin ihlal sayısını artıran sonuç reddedilir.
- İş sürerken program elle değiştirildiyse sonuç uygulanmaz (kullanıcının değişikliği ezilmesin).

**Çözülemezlik açıklaması:** `cpsat.explain` QuickXplain ile birlikte sağlanamayan en küçük kural kümesini bulur.

**Arka plan:** `TIMETABLE_JOB_BACKEND=thread` (yerel; web sürecinde iş parçacığı) ya da `worker`
(sunucu; `python manage.py calisan` ayrı süreç, veritabanı kuyruğu, nabız, durdurma isteği).
Çözücü iş parçacığı sayısı `SOLVER_WORKERS` (varsayılan çekirdek sayısı, 8–32).

## 6. Alınan kararlar ve nedenleri

| Karar | Neden |
|---|---|
| Sıfırdan üretimde **Katı mod + otomatik süre** | Büyük MYO verisinde en iyi sonucu veriyor; ihlaller önce sıfırlanıyor, ceza sonra düşürülüyor |
| Gen2 / Gen3 menüden kaldırıldı, kodu duruyor | Katı mod onarım + ceza düşürmeyle aynı işi görüyor; `gen2.py` ayrı bir çalışmada (Codex) geliştiriliyor — **dokunulmuyor, yalnızca çağrılıyor** |
| Ceza düşürmede "ceza ≤ eski − 1" kısıtı yok; kabul ölçütü sonradan | O kısıt ipucunu (hint) geçersiz kılıp turları sonuçsuz bırakıyordu |
| Kesin ihlal artıran sonuç asla yazılmaz | Ceza düşürme bazen ihlal pahasına ceza düşürebiliyordu |
| Uzun işler web isteği yerine kuyrukta | Vekil sunucu zaman aşımı ve sunucunun kilitlenmesi |
| Yetki URL adına göre tek ara katmanda, tabloda olmayan URL yalnızca süper kullanıcıya | Unutulan bir görünüm yetkisiz açık kalmasın |
| Başka kuruma ait hesabı kurum yöneticisi kendi kurumuna bağlayamaz | Hesap ele geçirme açığı (güvenlik düzeltmesi) |
| Parola sıfırlama bağlantısı yalnızca güvenilir adresle (`DJANGO_PUBLIC_URL`) | Host başlığı zehirleme |
| Etkinlik / telafi tarihe bağlı tek seferlik kayıt; haftalık programa kart olarak girmez | Haftalık program bozulmasın; meşguliyet = o günün kartları + vekâletler + devamsızlık + yasak + diğer etkinlikler |
| Telafi **karma grup** olabilir (birden çok ders/kısım + ek sınıf/grup/öğrenci + başka öğretmen) | Kullanıcı isteği: farklı kısımların telafisi tek oturumda |

## 7. Bilinen sınırlar / açık işler

- Doluluğu %100 olan kısımlarda hafta içi telafi saati çıkmaz → "hafta sonunu da ara" seçeneği var
  (pazar da aranıyor; kullanıcı seçiyor).
- Etkinlik/telafi aramasında A/B haftası ayrımı yok (dersin olduğu her hafta dolu sayılır).
- Seçimlerden şube açma yeni şubeyi ilk şubenin öğretmeniyle açar; programa girmesi için yeniden üretim gerekir.
  Tarayıcıda gerçek veriyle denenmedi (yalnızca testli).
- Derin "İhlalleri çöz" (gün komşuluğu) kaynak çakışmalarını onaramaz; onlar az değişiklikli onarımla çözülür.
- Çok süreçli dağıtık iş kuyruğu (Celery/RQ) yok; `worker` kipi tek çalışan süreçle sırayla çalışır.
- Arayüz yalnızca Türkçe; çoklu dil altyapısı yok.

## 8. Başka bir projeye bağlama

### Seçenek A — Ana proje de Django ise (en sıkı bütünleşme)

1. `timetable/` ve `sinav/` klasörlerini ana projeye kopyala (ya da bu depoyu alt modül olarak ekle). Sınav
   Planlama istenmiyorsa `sinav/` alınmaz; Ders Planlama tek başına çalışır.
2. `requirements.txt` bağımlılıklarını ekle.
3. Ayarlar (bkz. `config/settings.py`):
   ```python
   INSTALLED_APPS += ["timetable", "sinav"]
   # Sıra önemli: AuthenticationMiddleware → LoginRequiredMiddleware → SchoolAccessMiddleware.
   # Modül Django 5.1+'ın LoginRequiredMiddleware'ine güvenir: giriş istemeyen görünümler (web yayını,
   # takvim aboneliği, parola sayfaları) @login_not_required ile işaretli. Ana projede bu ara katman yoksa
   # modülün sayfaları girişsiz açılır — mutlaka eklenmeli.
   MIDDLEWARE += ["django.contrib.auth.middleware.LoginRequiredMiddleware",
                  "timetable.access.SchoolAccessMiddleware"]
   TEMPLATES[0]["OPTIONS"]["builtins"] = ["timetable.templatetags.search"]
   TEMPLATES[0]["OPTIONS"]["context_processors"] += ["timetable.access.can"]
   TIMETABLE_SOLVER_TIME_LIMIT = 60
   TIMETABLE_RUN_IN_BACKGROUND = True
   TIMETABLE_JOB_BACKEND = "worker"    # sunucuda; ayrıca `manage.py calisan` sürecini çalıştır
   BACKUP_DIR = ...; BACKUP_KEEP = 30; AUTO_BACKUP = False   # yedeği ana proje yapıyorsa
   PUBLIC_URL = "https://..."          # parola bağlantıları için
   ```
4. URL: `path("planlama/sinav-planlama/", include("sinav.urls"))` ve `path("planlama/", include("timetable.urls"))`
   (sinav önce). Ana projenin kendi ana sayfası varsa modül kartları oradan `timetable.modules.user_modules(user)`
   ile üretilebilir. Modül kendi `login` sayfasını içerir; ana projenin
   girişini kullanmak için `LOGIN_URL` ana projeninki yapılabilir. Şablon ve JS adresleri `{% url %}` ile
   üretiliyor, sabit `/okul/...` yolu yok — önek altında çalışması beklenir ama **denenmedi**.
5. Kullanıcı: ana proje özel kullanıcı modeli (`AUTH_USER_MODEL`) kullanıyorsa `models.py` ve
   `sinav/models.py`'deki `"auth.User"` başvuruları `settings.AUTH_USER_MODEL` yapılmalı (migration'lar zaten uyumlu).
6. Yetki: modülün kendi `Institution` / `Membership` yapısı var. Ana projede kurum/okul ve rol varsa ya
   eşleştirme (ana projede kurum açılınca `Institution` + `Membership` oluşturan sinyal) ya da `access.py`'deki
   `school_permissions` / `institution_permissions` fonksiyonlarını ana projenin rollerine bağlama gerekir.
   **Asıl tasarım kararı budur.**
7. Görünüm: `templates/timetable/base.html` kendi menüsü ve temasıyla tam sayfadır. Ana projenin
   iskeletine uymak için `base.html` ana projenin şablonunu genişletecek şekilde değiştirilebilir.
8. Bağımsız kuruluma ait parçalar ana projede **kapatılmalı/çıkarılmalı:** `baslat.py`, `updater.py`
   (Merkez → Sistem güncelleme; git pull + yeniden başlatma yapar), `backup.py` otomatik yedeği,
   `config/`, `.bat/.sh` betikleri.
9. Testler: `python manage.py test timetable sinav --parallel 1` ana projede de geçmeli.

### Seçenek B — Ana proje başka teknolojiyle (ayrı servis)

Modül bağımsız bir Django uygulaması olarak kendi sunucusunda / kapsayıcısında çalışır
([../YAYIN.md](../YAYIN.md), `docker compose up -d`), ana proje ona bağlantı verir (alt alan adı ya da ters
vekil altında yol). Veri alışverişi için hazır kapılar:
- Web yayını (`public.py`): giriş gerektirmeyen, gizli bağlantılı program ve günlük vekâlet ekranı.
  Başka alan adından iframe ile gömülecekse `XFrameOptionsMiddleware` yüzünden engellenir; bu sayfalara
  `xframe_options_exempt` (ya da CSP `frame-ancestors`) eklemek gerekir.
- Dışa aktarma: Excel, aSc XML, PDF; içe aktarma: Excel, aSc XML.
- Öğretmen telefon takvimi (abonelik bağlantısı, `teacher_calendar.py`).
- Ortak giriş (SSO) yok; gerekirse eklenmesi gereken iş.

## 9. Gerçek veri ve gizlilik

- `db.sqlite3` ve `yedekler/` gerçek öğretmen ve öğrenci adları, öğretmen TC kimlik numaraları içerir.
  Git'e girmez ve **devirde paylaşılmamalıdır.** Deneme için `python manage.py seed_demo`.
- Gerçek veriyle deneme gerekirse adları değiştirilmiş bir kopya hazırlanmalı.

## 10. Devralan Claude için başlangıç

İlk mesaj önerisi:

> `dersprogrami/docs/MODUL-DEVIR.md` ve `dersprogrami/CLAUDE.md` dosyalarını oku. Bu modül benim projemin
> bir parçası olacak; projem şu teknolojiyle yazılıyor: … Bütünleşme için §8'deki seçeneklerden hangisinin
> uygun olduğunu, ana projedeki kullanıcı/kurum yapısıyla nasıl eşleşeceğini öner. Kod yazmadan önce planı göster.

Ezbere bilinmesi gereken tuzaklar:
- Yeni URL → `access.py` tablosu ya da modülün `module.py`'sindeki `routes` (yoksa 403).
- Çözücü testleri yavaş; tüm paket ~10 dk. Değişen alanın test dosyasını önce tek başına çalıştır.
- `gen2.py`'ye dokunma.
- Sunucuda yeni migration'lar başlatıcı (`baslat.py`) ya da `manage.py migrate` ile uygulanır.
