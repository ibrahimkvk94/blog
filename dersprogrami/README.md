# Ders Programı

aSc TimeTables mantığıyla çalışan, Django tabanlı otomatik okul ders programı sistemi.
Tasarımın gerekçeleri için: [`../docs/asc-timetables-analizi.md`](../docs/asc-timetables-analizi.md).

## Kurulum

```bash
cd dersprogrami
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo                    # örnek lise: 4 şube, 15 öğretmen, 116 kart
python manage.py generate_timetable 1         # komut satırından üretim
python manage.py createsuperuser              # veri girişi için admin kullanıcısı
python manage.py runserver
```

- `http://localhost:8000/` — okullar, veri denetimi, program üretme, sınıf/öğretmen/derslik görünümleri
- `http://localhost:8000/admin/` — veri girişi

Ortam değişkenleri: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (`1`/`0`), `DJANGO_ALLOWED_HOSTS`,
`TIMETABLE_SOLVER_TIME_LIMIT` (saniye, varsayılan 60).

Testler: `python manage.py test timetable`

## Kavramlar

| Kavram | Anlamı |
|---|---|
| **Ders (Lesson)** | Ders adı + sınıf(lar)/grup(lar) + öğretmen(ler) + olası derslikler + haftalık saat + kart uzunluğu |
| **Kart (Card)** | Dersin tek oturumu. Haftada 6 saat ve uzunluk 2 olan bir ders 3 kart (blok ders) üretir |
| **Bölünme / Grup** | Sınıfı tamamen kapsayan gruplar (ör. Almanca/Fransızca). Aynı bölünmedeki gruplar aynı anda ders görebilir; farklı bölünmelerdekiler çakışır |
| **Birleşik ders** | Birden çok sınıfı/grubu olan ders (ör. 9-A ve 9-B'nin Almanca grupları birlikte) |
| **Müsaitlik** | Öğretmen/sınıf/derslik/ders adı/ders için gün×saat hücresi: yasak ya da koşullu (?) |
| **Program (Timetable)** | Bir üretimin sonucu (sürüm). Kilitli kartlar sonraki üretimlerde yerinde kalır |
| **Hafta / dönem maskesi** | A/B haftası ya da dönemlik dersler. İki kart yalnızca ortak bir hafta-dönemde çakışabilir |

## Mimari

```
timetable/
  models.py            veri modeli
  solver/              Django'dan bağımsız çözücü katmanı
    problem.py         sade problem yapısı, öğrenci "atomları"
    builder.py         veritabanı → Problem
    feasibility.py     üretim öncesi veri denetimi (kesin imkânsızlıkları açıklayarak bildirir)
    cpsat.py           OR-Tools CP-SAT modeli
    validate.py        çözücüden bağımsız doğrulama (elle düzenlenmiş programlar için de)
  services.py          denetim / üretim / doğrulama işlemlerini veritabanına bağlar
  views.py, templates/ web arayüzü
  demo.py              örnek okul verisi
```

**Öğrenci atomları:** Her sınıf, bölünmelerinin gruplarının kartezyen çarpımı kadar atoma ayrılır
(ör. {Kız, Erkek} × {Almanca, Fransızca} → 4 atom). Her grup bir atom kümesidir. İki ders ancak
atom kümeleri kesişiyorsa çakışır. Böylece bölünme kuralları tek ve genel bir kurala iner.

### Kısıtlar

Sert kısıtlar:
- her kart tam bir kez yerleşir; blok kartlar ardışık saatleri kaplar ve gün sonunu aşmaz
- öğretmen, öğrenci atomu ve derslik çakışmaz (ortak hafta-dönem içinde)
- yasak müsaitlik hücreleri kullanılmaz
- derslik birden çok seçenekten birine atanır
- aynı dersin kartları günde en fazla N (varsayılan: mümkün olduğunca farklı günler)
- öğretmen: günde en fazla ders, günde/haftada en fazla boşluk
- kilitli kartlar yerinde kalır

Yumuşak kısıtlar (ceza puanı):

| Ağırlık | Kural |
|---|---|
| 100 | sınıf (atom) programında boşluk |
| 50 | sınıfın güne ilk saatten başlamaması |
| 10 | öğretmen boşluğu |
| 5 | koşullu (?) hücre kullanımı |

## Yol haritası

- [x] Veri modeli, admin ile veri girişi
- [x] Üretim öncesi veri denetimi
- [x] CP-SAT ile üretim, kilitli kartlar, önceki sürümden ipucu
- [x] Bağımsız doğrulama raporu; sınıf, öğretmen ve derslik görünümleri
- [ ] Arka planda üretim (Celery/RQ) ve canlı ilerleme
- [ ] Kart ilişkileri (aynı anda, farklı günler, ardışık…) için genel kural dili
- [ ] Kısıt gevşetme modları ve çözülemezlik çekirdeği açıklaması
- [ ] Sürükle-bırak düzenleme, hücre uygunluk renklendirmesi, hızlı sezgisel onarım
- [ ] aSc XML içe/dışa aktarım, PDF/Excel çıktıları
- [ ] Seminer (öğrenci seçimli) dersler, günlük vekâlet modülü
