from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.decorators import action
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import IncidentReport


@admin.register(IncidentReport)
class IncidentReportAdmin(BuildingScopeMixin, ModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "category_badge", "severity_badge", "description_short",
                    "handled", "created_at"]
    list_filter = ["category", "severity", "handled", "created_at"]
    search_fields = ["resident__name", "description"]
    list_per_page = 30
    date_hierarchy = "created_at"
    autocomplete_fields = ["resident", "handled_by_emp"]
    actions = ["mark_handled"]

    @admin.display(description=_("类型"))
    def category_badge(self, obj):
        return obj.get_category_display()

    @admin.display(description=_("严重程度"))
    def severity_badge(self, obj):
        return obj.get_severity_display()

    @admin.display(description=_("摘要"))
    def description_short(self, obj):
        return obj.description[:60] + "…" if len(obj.description) > 60 else obj.description

    @action(description=_("标记为已处理"))
    def mark_handled(self, request, queryset):
        queryset.update(handled=True, handled_at=timezone.now())
