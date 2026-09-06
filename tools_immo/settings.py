"""
Django settings for tools_immo project.

Application locale d'aide au montage de dossier de prêt immobilier
(analyse de relevés, charges fixes, simulateur). Elle ne persiste aucune
donnée métier : tout se passe en mémoire et en session (cookies signés).
Aucune base de données n'est nécessaire à son fonctionnement.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY : surchargée par l'environnement en déploiement. La valeur par
# défaut ne sert qu'au développement local.
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-8k2m$e1r!p7w0q9zx4c6v3n5b#t00ls-1mmo-dev-only',
)

DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'

ALLOWED_HOSTS = os.environ.get(
    'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')


# Application definition. L'appli ne persiste rien et n'a ni comptes ni admin :
# les apps intégrées auth/contenttypes/sessions (qui exigeraient des migrations
# et une base) sont retirées. Les sessions passent par des cookies signés, donc
# SessionMiddleware suffit sans l'app « sessions ».
INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'analyseur_bancaire',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'tools_immo.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'tools_immo.wsgi.application'


# Aucune donnée métier persistée : les sessions et les messages passent par des
# cookies signés côté client, donc l'application tourne sans base. Une entrée
# « default » factice reste exigée par Django mais n'est jamais sollicitée en
# usage normal (elle ne sert qu'à un éventuel `migrate` des apps intégrées).
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'


# Internationalisation
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True


# Fichiers statiques et media
STATIC_URL = 'static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Taille max des fichiers uploadés (10 Mo)
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
