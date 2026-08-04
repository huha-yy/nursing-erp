import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nursing_erp.settings")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")

django.setup()
