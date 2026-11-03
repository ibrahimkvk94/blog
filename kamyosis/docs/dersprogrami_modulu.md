# Ders Programı modülü (timetable + sinav)

Haftalık ders programını hazırlayan ve otomatik üreten modül (CP-SAT çözücü), sınav programı, etkinlik/telafi ve
derslik ayırma, girişsiz web yayını. İbrahim'in projesidir; KAMYOSİS ile **ortak depoda** birlikte geliştirilir.

- **Ortak depo:** `ibrahimkvk94/blog` (herkese açık), dal `claude/elegant-fermi-mtxjbt`. Modül `dersprogrami/`
  (bağımsız kurulumu da çalışır), KAMYOSİS `kamyosis/` klasöründedir. KAMYOSİS modülü kopyalamaz; `dersprogrami/`
  klasörünü Python yoluna ekleyerek kullanır (`config/dersprogrami_yolu.py`). Bu bilgisayarda yol
  `.dersprogrami_yolu` dosyasında yazılıdır.
- **Depoya veri girmez:** veritabanı, yedekler, kayıtlar, parola dosyaları ve aSc/Excel aktarımları `.gitignore`'dadır.
- **Modüller:** modül iki Django uygulamasıdır: `timetable` = **Ders Planlama** ve ortak veri (kurum, program, sınıf,
  öğretmen, derslik, ders), `sinav` = **Sınav Planlama**.
- **Adres:** `/ders-programi/` (modüllerin ana sayfası), `/ders-programi/ders-planlama/`, `/ders-programi/sinav-planlama/`.
  Menüde: Öğrenci İşleri → Plan Program Kısmı → **Program Hazırlama** (Ders Planlama) ve **Sınav Planları** (Sınav Planlama).

## Yetkiler

Modülün kendi kullanıcı ve yetki ekranları kapalıdır. Yetki, KAMYOSİS yönetim panelinden birimlere verilir;
modül üyelikleri (`timetable.Membership`) bunlardan otomatik üretilir (`dersprogrami_kopru/yetki.py`).

| KAMYOSİS yetkisi | Modülde |
|---|---|
| Program Hazırlama: Görüntüleme (ya da kapsamı "bölüm") | Ders Planlama: programları ve raporları görür |
| Program Hazırlama: Düzenleme | + veri girişi (sınıf, öğretmen, ders…), etkinlik ve telafi |
| Program Hazırlama: Yönetim | + program üretme, yayınlama, program ekleme/silme/aSc'den alma |
| Sınav Planları: Görüntüleme / Düzenleme | Sınav Planlama: sınav programını görür / hazırlar |

Üyelikteki modül kısıtı (`Membership.modules`) da buradan yazılır: Program Hazırlama yetkisi → `ders`, Sınav Planları
yetkisi → `sinav`. Program Hazırlama yetkisi Sınav Planlama'yı açmaz; sınavda değişiklik yalnızca Sınav Planları'nda
Düzenleme ile yapılır (`dersprogrami_kopru/middleware.py` → `_sinav_yetkisi`).

Yalnızca Sınav Planları yetkisi olan hesap (ör. bölüm hesapları) modülde yalnızca Sınav Planlama sayfalarını açar:
menüde "Ortak veri" dahil Ders Planlama bağlantıları, ana sayfa/Kurumlarım ve arama gizlenir; Ders Planlama adresleri
(ortak veri sayfaları dahil) Sınav Planları'na yönlendirilir (`middleware.py` → `sadece_sinav`, `apps.py`).

Üst birime (Plan Program Kısmı, Öğrenci İşleri Şube) verilen yetki alt birimlere geçer. Süper kullanıcı her şeyi yapar.
Eşitleme yetki değişince kendiliğinden olur; elle: `manage.py ders_programi_yetki_esitle`.

## Künye (rütbe, sınıf, unvan)

Modüldeki öğretmenin "ünvan / rütbe" alanı KAMYOSİS personelinden yazılır (`dersprogrami_kopru/kunye.py`),
PPYS kuralıyla (`V47Birlestir`): unvan "önde" ise `Unvan SınıfRütbe`, değilse `SınıfRütbe Unvan`; sınıf ile
rütbe bitişik (ör. "Dr.Öğt.Üyesi Öğ.Yb.", "Öğ.Ütğm. Dr."). "Önde" bilgisi Yönetim Paneli → Seçenekler'deki
"Unvan önde" işaretidir. Öğretmen ad soyadla eşleşir (T.C. kimlik no kullanılmaz). Personel, seçenek, aSc
eşleşmesi ya da modüldeki öğretmen değişince kendiliğinden; elle `manage.py ders_programi_kunye_esitle`
(sunucu açılışında da çalışır). Modülde bu alan elle değiştirilirse KAMYOSİS'teki değerle üzerine yazılır.

## Sınav Planlama: KAMYOSİS kuralları (program bazlı)

03.11.2026'da istenen kurallar ortak koddaki `sinav` uygulamasına eklendi (`dersprogrami/sinav/kurallar.py`):

1. Sınavlar **ders koduna** (ders adının kısa adı, aSc kodu) göre oluşur; aynı kodlu kısımlar tek sınavdır.
2. Sınav türü **%100 UYG** olan dersler plana alınmaz (oluşturmada atlanır, sonradan UYG yapılırsa çözüme girmez).
3. Kontenjan **program × sınıf düzeyine** girilir (ör. SVN 1. sınıf: 120) ve programın kısımlarına eşit bölünerek
   sınıfın "öğrenci sayısı" alanına yazılır; sınav öğrenci sayısı ve salon dağıtımı bundan hesaplanır. Kısmın programı
   (`SchoolClass.program`) ve düzeyi kısa adından bir kez atanır: "10MKT" → MKT, numara 1–36 → 1. sınıf, 50–86 → 2. sınıf.
4. **Zorluk** 1–5 (girilmezse 3): zor sınav mümkün olduğunca erken güne; eşit zorlukta MT içeren türler önce, ÇS sona.
5. Adı aynı (parantez içi hariç) sınavlar aynı güne.
6. Bir oturumda mümkün olduğunca tek **sınıf düzeyi** (3 haneli ders numarasının ilk rakamı: BİL103 → 1. sınıf).

Tür ve zorluk kurum düzeyinde ders koduyla tutulur (`ExamCourse`); "Ders sınav bilgileri" sayfasından elle ya da
Excel'den girilir, Excel'e aktarılır (`sinav/ders_bilgileri.py`). 4–6 çözücünün zamanlama aşamasında tercihtir
(`solver._kamyosis_terms`; ağırlıklar `W_ORDER`, `W_SAME_NAME_DAY`, `W_MIXED_YEAR`). Öğrenci bazlı planlama
henüz yapılmadı.

## Sınav görevleri: mazeret, roller, puantaj (PPYS SMS / SPS / STS)

- **Sınav mazereti** (KAMYOSİS `mazeret` uygulaması, Plan Program → Mazeretler → Sınav Mazeretleri): dönem, Sınav
  Planlama'daki bir sınav dönemine bağlanır (Yönetim Paneli → Sınav mazeret dönemleri). Izgara = dönemin günleri ×
  oturum saatleri; ✗ görev verilemez, ? mümkünse verilmesin. Her kayıt dönemin `proctor_blocks` / `proctor_soft`
  alanına yazılır (eşleme ad soyadla). Sınav programı oluşturulmadan hemen önce (ve "Eksikleri otomatik ata"da)
  köprü dönemin tamamını yeniden aktarır: bildirimi olmayan personelin tüm oturumları kapanır (dönem ayarı), personelin
  görev rolleri `proctor_roles`'e yazılır ve rol kuralı (`duty_roles`) açılır.
- **Görev rolleri** (ortak kod): rol kuralı açık dönemde salon başına 40 ve üstü öğrencide 1 salon amiri; 40'tan azda 1,
  fazlasında her 20 öğrenciye 1 gözetmen; öğrencisi olan salona 1 taşıyıcı (`solver.duty_need`). Personelin
  alabileceği roller KAMYOSİS'te `Personel.sinav_rolleri` (varsayılan "GT"; boş = görev verilmez), puantaj sayfasından
  değiştirilir. Görevlinin rolü `ExamRoom.roles`'tadır (kayıt yok = gözetmen).
- **Puantaj** (KAMYOSİS `sinavgorev`, Plan Program → Sınav Görev Puantajı): sınav dönemi "puantaja işlenince" görevleri
  `SinavGorevi` olarak kopyalanır (her oturum ayrı görev); Sınav Planlama dışındaki görevler elle eklenir. Hafta içi 1,
  hafta sonu 1,5 puan; yıl 1 Ekim'de başlar. Skor = puan + z (haftalık ders saatinin z puanı, seçilen programdan).
- **Salon amiri kuralı**: puantaj sayfasındaki "Kurala göre salon amiri ata", unvanı Dr.Öğt.Üyesi / Doç.Dr. /
  Prof.Dr. ya da rütbesi Yzb. üstü (Bnb. ve yukarısı) olan personele A rolü ekler; kalan düzenleme elle yapılır.
- **Görev değişikliği** (ortak kod, Sınav Planlama → dönem → "Görev değişikliği"): bir görevi başka öğretmene verme ya
  da iki görevi takas etme; uygunluk denetlenir, gerekçe zorunlu, her değişiklik `ExamDutyChange` olarak kaydedilir,
  sınav kilitlenir. Dönem puantaja işlenmişse köprü puantajı hemen yeniler.
- **Dengeli dağıtım**: `settings.SINAV_GOREVLI_PUANI` → `sinavgorev.servis.onceki_puanlar`; çözücü her öğretmenin yıl
  içindeki skorunun (dağıtılan dönem hariç) üstüne yükü eşitler, hafta sonu oturumunu 1,5 sayar, "?" oturumuna
  ancak gerekirse görev verir (`W_SOFT`).

## KAMYOSİS'e aktarım

Modülde bir program **yayınlandığında** KAMYOSİS'te otomatik olarak **taslak** bir program sürümü oluşur
(Ders Planları → Program sürümleri). Aynı program yeniden yayınlanırsa taslak yenilenir. KAMYOSİS'teki asıl yayın
(ders takibinin başlayacağı tarih) yine Ders Planları ekranından elle yapılır.

- Öğretmenler önce ada göre, olmazsa modüldeki TC kimlik numarasından personele bağlanır. TC aktarılmaz, yalnızca
  eşleme için kullanılır.
- A/B haftalı ya da dönemli dersi olan program aktarılmaz (ders takibi henüz desteklemiyor); modülde yayın yine yapılır.

## Kapalı bölümler

Sistem güncelleme, yedekleme/geri yükleme, merkez paneli, yeni kurum açma, kullanıcı/öğretmen hesapları, nöbet ve
vekâlet sayfaları KAMYOSİS'te kapalıdır (`dersprogrami_kopru/middleware.py` → `KAPALI`). Nöbet ve ders devri
KAMYOSİS'in kendi modülleriyle yapılır. "Yedekle karşılaştır" sayfası yalnızca "önceki başarılı üretimle karşılaştır"
için açıktır; yedeği yükleyen karşılaştırma kapalıdır.

## Testler

- `manage.py test dersprogrami_kopru` köprünün testleri; KAMYOSİS'in diğer uygulamalarıyla birlikte koşturulur.
- `manage.py test timetable sinav --parallel 1` modülün kendi testleri (yaklaşık 16 dk). 03.11.2026'da (`b3ab6a9`)
  557 testten **31'i beklenen nedenlerle düşer**: kapalı sayfaları (vekâlet, nöbet, merkez, kullanıcılar, hesaplar,
  parola sıfırlama, örnek okul, aSc'den yeni kurum) açmaya çalışırlar, sabit `/okul/...` adresi kullanırlar (modül
  KAMYOSİS'te `/ders-programi/` altındadır) ya da tek kurum varsayımına (KAMYOSİS kurumu migration ile açılır) takılırlar.
  Bu sayı artarsa yeni bir uyumsuzluk vardır.
- Yedek geri yükleme/karşılaştırma ve sistem güncelleme testleri KAMYOSİS'te atlanır (`TIMETABLE_GOMULU`): canlı
  veritabanına yükleyen ve `git reset --hard` yapan kodu çalıştırırlar.
- Ortak kodu değiştirince modülün bağımsız kurulumunda da test edin: `dersprogrami/` klasöründe
  `manage.py test timetable sinav --parallel 1` (hepsi geçmeli).

## Çalışma

- `yayinla.py` siteyle birlikte `manage.py calisan` sürecini başlatır; program üretimleri orada çalışır
  (kayıt: `kayitlar/calisan.log`). Çözücü çekirdek sayısının 2 eksiğini kullanır (`SOLVER_WORKERS`).
- `gelistir.bat` (geliştirme) üretimi web sürecinde çalıştırır; ayrı süreç gerekmez.
- Veritabanı WAL kipindedir. Yedek, dosya kopyalanarak değil **`yedekle.bat`** ile alınır (site çalışırken de olur).

## Ortak koddaki KAMYOSİS uyarlamaları

Modülün bağımsız kurulumunu bozmayan, KAMYOSİS'in ihtiyacı olan değişiklikler doğrudan ortak koddadır ("KAMYOSİS"
açıklamasıyla işaretli):

1. Kullanıcı modeli: `"auth.User"` → `settings.AUTH_USER_MODEL`, `User` içe aktarmaları → `get_user_model()`.
2. `timetable/access.py` (`SchoolAccessMiddleware._school`): 403 yanıtı önek altındaki `/api/` adreslerinde de JSON
   döner; köprünün verdiği ek yetki (`request.timetable_extra_perms`) hesaba katılır.
3. Yedek ve sistem güncelleme testleri `TIMETABLE_GOMULU` ayarı açıkken atlanır.
4. `sinav`: KAMYOSİS sınav kuralları (yukarıda) — `kurallar.py`, `ders_bilgileri.py`, `templates/sinav/courses.html`,
   `tests/test_kamyosis.py`, `migrations/0002_kamyosis_sinav_kurallari.py` ve işaretli yerler.
5. `sinav`: görev rolleri, "mümkünse verilmesin" oturumları, önceki puanla denge (yukarıda) —
   `migrations/0003_kamyosis_gorev_rolleri.py`, `solver.duty_need` ve gözetmen aşaması, `services.prior_scores` /
   `proctor_soft`, düzenleme ve Gözetmenler sayfalarında rol seçimi, çıktılarda rol adı.
6. `sinav`: görev değişikliği (`gorev_degisikligi.py`, `templates/sinav/duties.html`, `migrations/0004`), program
   kontenjanı ve Gözetmenlerde anında kayıt; `timetable`: `SchoolClass.program` (`migrations/0047`).

`templates/timetable/` altındaki `base.html`, `nav/ribbon.html`, `home.html`, `school_list.html`, `institution.html`
KAMYOSİS sürümleriyle ezilir; `araclar/dersprogrami/sablon_uyarla.py` ile modülün dosyalarından üretilir.

### Çalışma düzeni (ortak dal)

1. Değişiklikten önce dalı çekin: `git pull` (ortak deponun kökünde). İbrahim'in değişiklikleri gelir.
2. Modül değişikliği `dersprogrami/` altında, KAMYOSİS değişikliği `kamyosis/` altında yapılır.
3. Modülün şablonları değiştiyse `python araclar\dersprogrami\sablon_uyarla.py`; bulunamayan değişiklik varsa söyler.
4. `python manage.py makemigrations --check` (değişiklik çıkmamalı), KAMYOSİS testleri ve gerekirse modülün testleri.
5. Gerçek verinin kopyasında `migrate` deneyin, yedek alıp yayına alın; commit ve `git push`.
6. Aynı migration numarasıyla iki taraf migration eklerse `makemigrations --merge` gerekir.
