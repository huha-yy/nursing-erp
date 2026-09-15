from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BedsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "beds"
    verbose_name = _("床位管理")
