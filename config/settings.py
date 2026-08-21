"""Minimal Django settings for the HRIS Import Preview app.

Deliberately small: there is no database, no auth, and no deployment config.
Django is only here to accept a file upload and render two templates.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Fine for a local take-home. A real deployment would read this from the env.
SECRET_KEY = "django-insecure-hris-import-preview-local-only"
DEBUG = True
# Local-only take-home app: "testserver" is the host Django's own test client
# uses, so keeping it here lets the app be driven without a browser.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

INSTALLED_APPS = [
    # We only need staticfiles-free basics: sessions and messages are unused,
    # but contenttypes/auth are omitted entirely since there is no database.
    "django.contrib.staticfiles",
    "preview",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,  # templates live in preview/templates/preview/
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# No persistence anywhere in this app: the CSV is analyzed in memory and the
# result is rendered straight back to the browser.
DATABASES = {}

# Cap uploads at 10 MB. Roughly 100k HRIS rows fit well inside that, and it
# keeps a stray huge file from being read into memory.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
