from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AssessmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "assessments"
    verbose_name = _("评估管理")
