from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class ResidentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "residents"
    verbose_name = _("老人照护")
