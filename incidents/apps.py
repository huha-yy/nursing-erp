from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class IncidentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "incidents"
    verbose_name = _("异常记录")
