# Ders Programı

aSc TimeTables mantığıyla çalışan, Django tabanlı otomatik okul ders programı sistemi.
Tasarımın gerekçeleri için: [`../docs/asc-timetables-analizi.md`](../docs/asc-timetables-analizi.md).

## Kurulum

```bash
cd dersprogrami
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser              # giriş için (tüm sayfalar giriş ister)
python manage.py seed_demo                    # örnek lise: 4 şube, 15 öğretmen, 116 kart
python manage.py runserver
```

`http://localhost:8000/` adresinde giriş yapın. Tüm veri girişi uygulamanın kendi ekranlarından
yapılır (sol menü → Veri); yönetim paneli (`/admin/`) yalnızca ileri düzey işler için kalır.

### Kendi sunucunda yayına alma (Docker)

```bash
cd dersprogrami
docker build -t ders-programi .
docker run -d -p 8000:8000 -v ders-programi-veri:/data \
  -e DJANGO_SECRET_KEY="uzun-rastgele-bir-anahtar" \
  -e DJANGO_ALLOWED_HOSTS="okulum.example.com" \
  -e DJANGO_CSRF_TRUSTED_ORIGINS="https://okulum.example.com" \
  -e DJANGO_BEHIND_HTTPS_PROXY=1 \
  -e DJANGO_SUPERUSER_USERNAME=mudur -e DJANGO_SUPERUSER_PASSWORD="güçlü-bir-parola" \
  ders-programi
```

Veritabanı `/data` biriminde (SQLite) tutulur. Üretim işleri süreç içinde çalıştığı için imaj
gunicorn'u tek süreç ve 8 iş parçacığıyla başlatır; bunu artırmayın. Docker çalıştıran her
platformda (Render, Railway, Fly.io, kendi VPS'iniz) aynı imaj kullanılabilir; HTTPS'i platformun
ters vekili sağlar.

Komut satırından üretim: `python manage.py generate_timetable <okul_id> [--mode relaxed] [--time-limit 60]`

Ortam değişkenleri: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS`,
`TIMETABLE_SOLVER_TIME_LIMIT` (saniye, varsayılan 60), `TIMETABLE_RUN_IN_BACKGROUND` (`1`/`0`).

Testler: `python manage.py test timetable`

## Ekranlar

| Ekran | İçerik |
|---|---|
| **Veri girişi** | Okul ve ders saatleri (satır ekle/sil), ders adları, sınıflar (bölünme ve grup düzenleyici), öğretmenler (sınırlar), derslikler, binalar, kart ilişkileri. Öğretmen, sınıf, derslik ve ders adı formlarında tıklanarak düzenlenen müsaitlik ızgarası (uygun / yasak / koşullu) |
| **Dersler** | Sınıf ve öğretmene göre süzülen ders listesi, sınıf yükleri, ayrıntılı ders formu (birleşik sınıflar, gruplar, birden çok öğretmen/derslik, blok kartlar) |
| **Sınıf ders tablosu** | Bir sınıfın tek öğretmenli derslerini tek tabloda saat, blok, öğretmen ve derslik seçerek girme; başka sınıftan saatleri kopyalama; toplam saat / kapasite göstergesi |
| **Genel bakış** | Okul özeti, veri denetimi, program sürümleri, yeni üretim (katı/gevşek mod, süre, başlangıç sürümü) |
| **Ana görünüm** | Satırlarda sınıflar / öğretmenler / derslikler, sütunlarda gün × saat. Başlık ve satır adları sabit, tüm ızgara yatay ve dikey kaydırılır. Satır arama, üç yakınlaştırma düzeyi |
| **Kart düzenleme** | Kart sürüklenir ya da tıklanıp hedef hücreye tıklanır. Seçili kart için her hücre renklenir: uygun / uyarılı / çakışmalı (çakışan kartlar bekleyenlere düşer) / uygun değil. Kilitleme, programdan çıkarma, "Bekleyenleri yerleştir" |
| **Üretim ekranı** | Arka planda çalışan üretimin canlı ilerlemesi (süre, bulunan çözüm, en iyi ceza) ve "Durdur ve en iyisini al" |
| **Doğrulama** | Programın sert/yumuşak kural ihlalleri; her düzenlemeden sonra güncellenir |
| **Vekâlet** | Tarihe göre devamsızlık girişi, her ders saati için sıralı vekil önerisi, kaydetme ve yazdırma |
| **Dışa aktarma** | Excel (sınıf/öğretmen/derslik genel görünümleri + kart listesi), aSc TimeTables XML, sınıf ve öğretmen bazlı yazdırılabilir / PDF sayfalar |
| **İçe aktarma** | aSc TimeTables XML dosyasından okul verisi ve yerleşmiş kartlar |

## Kavramlar

| Kavram | Anlamı |
|---|---|
| **Ders (Lesson)** | Ders adı + sınıf(lar)/grup(lar) + öğretmen(ler) + olası derslikler + haftalık saat + kart uzunluğu |
| **Kart (Card)** | Dersin tek oturumu. Haftada 6 saat ve uzunluk 2 olan bir ders 3 kart (blok ders) üretir |
| **Bölünme / Grup** | Sınıfı tamamen kapsayan gruplar (ör. Almanca/Fransızca). Aynı bölünmedeki gruplar aynı anda ders görebilir; farklı bölünmelerdekiler çakışır |
| **Birleşik ders** | Birden çok sınıfı/grubu olan ders (ör. 9-A ve 9-B'nin Almanca grupları birlikte) |
| **Müsaitlik** | Öğretmen/sınıf/derslik/ders adı/ders için gün×saat hücresi: yasak ya da koşullu (?) |
| **Kart ilişkisi** | Seçilen kartlara toplu kural: günde en fazla N kart, farklı günlerde, art arda en fazla N saat, aynı anda. "Uygula": tüm seçime / her sınıfa / her öğretmene ayrı. Önem: kesin (sert) ya da yüksek/normal/düşük (ceza) |
| **Program (Timetable)** | Bir üretimin sonucu (sürüm). Yayınlanan sürüm vekâlet işlemlerinde esas alınır |
| **Hafta / dönem maskesi** | A/B haftası ya da dönemlik dersler. İki kart yalnızca ortak bir hafta-dönemde çakışabilir |

## Mimari

```
timetable/
  models.py            veri modeli
  solver/              Django'dan bağımsız çözücü katmanı
    problem.py         sade problem yapısı, öğrenci "atomları", kart ilişkisi tanımı
    builder.py         veritabanı → Problem
    feasibility.py     üretim öncesi veri denetimi (kesin imkânsızlıkları açıklayarak bildirir)
    cpsat.py           OR-Tools CP-SAT modeli (katı / gevşek mod, ilerleme, durdurma)
    validate.py        çözücüden bağımsız doğrulama (elle düzenlenmiş programlar için de)
  services.py          üretim, onarım ("bekleyenleri yerleştir"), doğrulama
  jobs.py              arka plan işleri (iş parçacığı; ilerleme ve durdurma bellekte)
  editing.py           kart için hücre uygunluğu, taşıma, programdan çıkarma
  grid.py              ana görünüm verisi
  substitutes.py       vekâlet önerileri
  asc_xml.py, excel.py içe/dışa aktarma
  views.py, urls.py    sayfalar ve JSON API
  templates/, static/  arayüz (harici bağımlılık yok)
```

**Öğrenci atomları:** Her sınıf, bölünmelerinin gruplarının kartezyen çarpımı kadar atoma ayrılır
(ör. {Kız, Erkek} × {Almanca, Fransızca} → 4 atom). Her grup bir atom kümesidir. İki ders ancak
atom kümeleri kesişiyorsa çakışır. Böylece bölünme kuralları tek ve genel bir kurala iner.

### Kısıtlar

Katı modda sert kısıtlar:
- her kart tam bir kez yerleşir; blok kartlar ardışık saatleri kaplar ve gün sonunu aşmaz
- öğretmen, öğrenci atomu ve derslik çakışmaz (ortak hafta-dönem içinde)
- yasak müsaitlik hücreleri kullanılmaz; derslik birden çok seçenekten birine atanır
- aynı dersin kartları günde en fazla N (varsayılan: mümkün olduğunca farklı günler)
- öğretmen: günde en fazla ders, günde/haftada en fazla boşluk, haftada en fazla gün
- önemi "kesin" olan kart ilişkileri; kilitli kartlar yerinde kalır

**Gevşek mod:** kaynak çakışmaları ve kilitli kartlar yine serttir; diğer sert kurallar ağır cezalı
kurala dönüşür ve sığmayan kartlar bekleyenlerde kalır. Böylece çözülemeyen veride bile en yakın
taslak ve kırılan kuralların listesi elde edilir.

Yumuşak kısıtlar (ceza puanı):

| Ağırlık | Kural |
|---|---|
| 10000 | yerleşmeyen kart (gevşek mod) |
| 1000 | gevşetilen sert kural (gevşek mod) |
| 300 / 60 / 15 | önemi yüksek / normal / düşük kart ilişkisi |
| 100 | sınıf (atom) programında boşluk |
| 50 | sınıfın güne ilk saatten başlamaması |
| 10 | öğretmen boşluğu |
| 5 | koşullu (?) hücre kullanımı |

## Bilinen sınırlar

- Arka plan üretimi aynı süreçte bir iş parçacığında çalışır; ilerleme ve durdurma bilgisi
  bellektedir. Birden çok uygulama süreciyle (ör. gunicorn çok işçili) çalışırken ilerleme ekranı
  başka süreçteki işi göremez; bu durumda Celery/RQ'ya geçilmelidir (`jobs.start`).

## Yol haritası

- [x] Veri modeli, admin ile veri girişi, üretim öncesi veri denetimi
- [x] CP-SAT ile üretim; kilitli kartlar, önceki sürümden ipucu
- [x] Arka planda üretim, canlı ilerleme, durdurma
- [x] Katı / gevşek mod, ceza dağılımı
- [x] Kart ilişkileri (günde en fazla N, farklı günler, art arda en fazla N, aynı anda), öğretmen gün sınırı
- [x] Ana görünüm (satır: sınıf/öğretmen/derslik, sütun: gün × saat), sürükle-bırak düzenleme, hücre uygunluk renklendirmesi, bekleyenleri yerleştirme
- [x] aSc XML içe/dışa aktarma, Excel, yazdırılabilir / PDF çıktılar
- [x] Vekâlet modülü
- [x] Veri giriş ekranları (okul ve saatler, ders adları, sınıflar ve bölünmeler, öğretmenler, derslikler, dersler, sınıf ders tablosu, kart ilişkileri, müsaitlik ızgarası)
- [x] Docker ile yayına alma
- [ ] Ders bazında müsaitlik ızgarası ve toplu içe aktarma (Excel'den öğretmen/ders listesi)
- [ ] Seminer (öğrenci seçimli) dersler ve öğrenci bazlı program
- [ ] Çözülemezlik çekirdeği açıklaması (hangi kural kümesi birlikte imkânsız)
- [ ] Çok süreçli dağıtım için Celery/RQ ile iş kuyruğu
