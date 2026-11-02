# Ders Programı modülü — Claude için çalışma kuralları

Bu klasör, Django + OR-Tools CP-SAT ile çalışan okul / MYO ders programı uygulamasıdır (Django uygulaması:
`timetable`). Modülün ne yaptığı, mimarisi, alınan kararlar ve başka bir projeye nasıl bağlanacağı:
**[docs/MODUL-DEVIR.md](docs/MODUL-DEVIR.md)** — bu klasörde ilk kez çalışıyorsan önce onu oku.
Ekran listesi ve kavramlar için [README.md](README.md).

## Dil ve üslup

- Arayüz, mesajlar, docstring ve yorumlar **Türkçe**. Kod adları (değişken, fonksiyon, model) İngilizce;
  URL yolları Türkçe (`etkinlik-ve-telafi/`, `ceza-dusur/`).
- Kullanıcıya görünen metinlerde teknik terim yerine okulun dili: "kart", "kısım/şube", "derslik", "boşluk",
  "kesin kural / ceza". "Constraint", "slack", "objective" gibi sözcükler arayüze çıkmaz.
- Çevredeki kodun yoğunluğunda yorum yaz; modül başında neden-öyle açıklayan bir docstring olur.

## Çalıştırma

```bash
cd dersprogrami
python -m venv .venv && .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo                            # örnek lise
python manage.py runserver
```

- Windows'ta konsol çıktısında Türkçe karakter için `PYTHONIOENCODING=utf-8`.
- Testler: `python manage.py test timetable --parallel 1` (≈560 test, 8–10 dk; çözücü testleri yavaş).
  Tek dosya: `python manage.py test timetable.tests.test_events`.
- Veritabanı yolunu değiştirmek için `DJANGO_DB_PATH` (gerçek veriye dokunmadan denemek için kopyasını kullan).

## Değiştirirken uyulacak kurallar

1. **Yetki tablosu:** Okul/program altındaki her yeni URL adı `timetable/access.py` içindeki tablolara
   (`SCHOOL_ROUTES`, `TIMETABLE_ROUTES` …) eklenmeli. Eklenmeyen URL yalnızca süper kullanıcıya açılır
   (güvenli varsayılan) — "sayfa bende çalışıyor, öğretmende 403" hatasının sebebi hep budur.
2. **Menü:** Yeni sayfa menüde görünecekse `timetable/templatetags/navigation.py`.
3. **Model değişikliği** → migration (`python manage.py makemigrations timetable`); numara sırası korunur.
4. **Çözücü katmanı** (`timetable/solver/`) Django'ya bağımlı değildir; içine model / ORM importu girmez.
   Veritabanı ↔ problem dönüşümü `solver/builder.py`, sonucu yazma `services.py`.
5. **Uzun işler web isteğinde çalışmaz:** üretim `jobs.py`, iyileştirme / "İhlalleri çöz" / "Cezayı düşür"
   `school_improve.py` + `quick_jobs.py` kuyruğunda (ImproveJob). Yeni uzun iş de bu kuyruğa girer.
6. **Programı yazan her işlem geri alınabilir olmalı** (`versions.py` sürüm kaydı; `services.write_placements`).
7. **`timetable/solver/gen2.py` dosyasına dokunma** — o kısım ayrı yürüyor (Codex). Yalnızca çağrılır.
8. Kesin kural ihlali artıran bir sonuç asla programa yazılmaz (bkz. `services.penalty_search` koruması).

## Kişisel veri

`db.sqlite3` ve `yedekler/` gerçek öğretmen / öğrenci adları ve TC kimlik numaraları içerebilir; git'e
girmez (`.gitignore`). Bunları paylaşma, commit etme, dışarı gönderme. Deneme için `seed_demo` kullan.
