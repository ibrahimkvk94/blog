"""Ders programı (timetable) projesinin ayarları.

Gizli değerler ortam değişkenlerinden okunur; geliştirme için güvenli varsayılanlar vardır.
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Proje klasöründeki .env (ANAHTAR=değer satırları) ortam değişkeni olarak okunur; gerçek ortam
    değişkenleri önceliklidir. Kapalı ağ paketi gizli anahtarı ve ağ ayarlarını buraya yazar."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


_load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "timetable",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "timetable.access.SchoolAccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Üretimde statik dosyaları whitenoise sunar; geliştirmede runserver sunar.
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "timetable.access.can",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

def _database():
    """DATABASE_URL verilirse PostgreSQL (çok kullanıcılı sunucu), yoksa yerel SQLite dosyası.

    Ör. DATABASE_URL=postgres://kullanici:parola@db:5432/dersprogrami
    """
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith(("postgres://", "postgresql://")):
        parsed = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
        }
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "db.sqlite3"),
        # Ağdaki birçok kullanıcı ve arka plan üretimi aynı anda yazabilir:
        # WAL kipinde okumalar yazmayı beklemez; IMMEDIATE işlemler yazma kilidini baştan alır
        # (okumadan yazmaya geçerken "database is locked" hatası olmaz); kilit için 20 sn beklenir.
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=20000;",
        },
    }


DATABASES = {"default": _database()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Ters vekil (reverse proxy) arkasında HTTPS ile yayın için.
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if os.environ.get("DJANGO_BEHIND_HTTPS_PROXY") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Tüm sayfalar giriş gerektirir; giriş için yönetim panelinin giriş sayfası kullanılır.
LOGIN_URL = "timetable:login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "timetable:login"

# Çözücünün varsayılan süre sınırı (saniye).
TIMETABLE_SOLVER_TIME_LIMIT = int(os.environ.get("TIMETABLE_SOLVER_TIME_LIMIT", "60"))
# Web arayüzünden başlatılan üretimler arka planda (ayrı iş parçacığında) çalışır.
TIMETABLE_RUN_IN_BACKGROUND = os.environ.get("TIMETABLE_RUN_IN_BACKGROUND", "1") == "1"
# "thread": üretim web sürecinde çalışır (yerel kurulum). "worker": üretimler veritabanında sıraya
# girer ve ayrı `python manage.py calisan` süreci çalıştırır (sunucu kurulumu; web yeniden başlasa da sürer).
TIMETABLE_JOB_BACKEND = os.environ.get("TIMETABLE_JOB_BACKEND", "thread")

# Yedekler (merkez paneli → Yedekler ya da `python manage.py yedekle`)
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", BASE_DIR / "yedekler"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "30"))

# E-posta (program değişikliği ve vekâlet bildirimleri). EMAIL_HOST verilmezse bildirim gönderilmez.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL") == "1"
EMAIL_USE_TLS = not EMAIL_USE_SSL and os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "ders-programi@localhost")
