"""KAMYOSİS ayarları.

Ortam değişkenleri:
  KAMYOSIS_DEBUG          "1" geliştirme modu (varsayılan), "0" ağ üzerinden yayın
  KAMYOSIS_ALLOWED_HOSTS  virgülle ayrılmış adresler (varsayılan: hepsi, sadece kurum içi ağ için)
  KAMYOSIS_SECRET_KEY     verilmezse .secret_key dosyasından okunur / ilk çalışmada üretilir
  KAMYOSIS_DERSPROGRAMI   Ders Programı modülünün klasörü (bkz. config/dersprogrami_yolu.py)
"""

import os
import sys
from pathlib import Path

from django.core.management.utils import get_random_secret_key

from .dersprogrami_yolu import bul as _dersprogrami_yolu

BASE_DIR = Path(__file__).resolve().parent.parent

# Ders Programı modülü (timetable, sinav) ortak depodaki dersprogrami/ klasöründen kullanılır. Yol listenin sonuna
# eklenir: modülün kendi config/ paketi KAMYOSİS'inkini gölgelemesin.
DERSPROGRAMI_DIR = _dersprogrami_yolu(BASE_DIR)
if str(DERSPROGRAMI_DIR) not in sys.path:
    sys.path.append(str(DERSPROGRAMI_DIR))


def _secret_key():
    if os.environ.get("KAMYOSIS_SECRET_KEY"):
        return os.environ["KAMYOSIS_SECRET_KEY"]
    path = BASE_DIR / ".secret_key"
    if not path.exists():
        path.write_text(get_random_secret_key(), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("KAMYOSIS_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("KAMYOSIS_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "core",
    "personel",
    "program",
    "takip",
    "nobet",
    "aktarim",
    "mazeret",
    "sinavgorev",
    "timetable",  # Ders Programı modülü: Ders Planlama + ortak veri (bkz. docs/dersprogrami_modulu.md)
    "sinav",  # Ders Programı modülü: Sınav Planlama
    "dersprogrami_kopru",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Giriş yapmadan yalnızca @login_not_required sayfalar açılır (giriş, modülün web yayını)
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "dersprogrami_kopru.middleware.KopruMiddleware",
    "timetable.access.SchoolAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "builtins": ["timetable.templatetags.search"],
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation",
                "timetable.access.can",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        # KAMYOSIS_DB: deneme için başka bir veritabanı dosyası (ör. gerçek verinin kopyası)
        "NAME": os.environ.get("KAMYOSIS_DB") or BASE_DIR / "db.sqlite3",
        # Web sunucusu ve ders programı üreten çalışan süreç aynı anda yazar: WAL kipinde okumalar yazmayı
        # beklemez, IMMEDIATE işlemler yazma kilidini baştan alır, kilit için 20 sn beklenir.
        # Not: WAL açıkken yedek dosya kopyalanarak değil `yedekle.bat` ile alınır.
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=20000;",
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:panel"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Oturum: tarayıcı kapanınca biter, 8 saat hareketsizlikte düşer
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True

# Kurum kimliği (şablonlarda kullanılır)
KURUM_ADI = "Kara Astsubay Meslek Yüksekokulu"
SISTEM_ADI = "KAMYOSİS"

# --- Ders Programı modülü (timetable) ---
# "thread": üretim web sürecinde çalışır (geliştirme). yayinla.py "worker" yapar ve ayrı `manage.py calisan`
# sürecini başlatır; böylece uzun üretimler siteyi yavaşlatmaz ve sunucu yeniden başlasa da sürer.
SINAV_GOREVLI_PUANI = "sinavgorev.servis.onceki_puanlar"  # gözetmen dağıtımı yıl içindeki görev skoruna göre dengelenir
TIMETABLE_GOMULU = True  # modül başka projeye gömülü: yedek/güncelleme testleri atlanır
TIMETABLE_JOB_BACKEND = os.environ.get("TIMETABLE_JOB_BACKEND", "thread")
TIMETABLE_RUN_IN_BACKGROUND = True
TIMETABLE_SOLVER_TIME_LIMIT = int(os.environ.get("TIMETABLE_SOLVER_TIME_LIMIT", "60"))
# Modülün kendi yedekleme ekranı kapalı; üretim öncesi otomatik yedek de kapalı (KAMYOSİS yedeği kullanılır)
AUTO_BACKUP = False
BACKUP_DIR = BASE_DIR / "kayitlar" / "dersprogrami_yedek"
BACKUP_KEEP = 10
PUBLIC_URL = os.environ.get("KAMYOSIS_PUBLIC_URL", "").rstrip("/")
# E-posta bildirimleri: EMAIL_HOST verilmezse gönderilmez
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "kamyosis@localhost")