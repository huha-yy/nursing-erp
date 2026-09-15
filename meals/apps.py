from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class MealsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "meals"
    verbose_name = _("膳食点餐")
