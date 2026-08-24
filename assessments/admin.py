from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Assessment, AssessmentItem, AssessmentScore, GradeLevelMap


@admin.register(AssessmentItem)
class AssessmentItemAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["dimension_display", "name", "max_score", "order", "is_active"]
    list_filter = ["dimension", "is_active"]

    @admin.display(description="一级指标", ordering="dimension")
    def dimension_display(self, obj):
        return obj.get_dimension_display()


@admin.register(GradeLevelMap)
class GradeLevelMapAdmin(ModelAdmin):
    list_display = ["grade", "care_level"]


class AssessmentScoreInline(admin.TabularInline):
    """查阅用 view-only inline——明细只经页面/API 录入，后台不可改。"""
    model = AssessmentScore
    extra = 0
    can_delete = False
    fields = ["item", "score"]
    ordering = ["item__order"]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Assessment)
class AssessmentAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = [
        "resident", "assess_date", "total_score", "grade_display",
        "suggested_level", "status_display", "final_level", "confirmed_by",
    ]
    list_filter = ["status", "grade", "assess_date"]
    search_fields = ["resident__name"]
    autocomplete_fields = ["resident", "assessor1_emp"]
    date_hierarchy = "assess_date"
    inlines = [AssessmentScoreInline]
    actions = ["action_confirm"]
    readonly_fields = [
        "total_score", "grade", "suggested_level", "status",
        "final_level", "confirm_reason", "confirmed_by", "confirmed_at",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("resident", "assessor1_emp")

    @admin.display(description="能力等级", ordering="grade")
    def grade_display(self, obj):
        return Assessment.GRADE_LABELS[obj.grade]

    @admin.display(description="状态", ordering="status")
    def status_display(self, obj):
        return obj.get_status_display()

    def get_readonly_fields(self, request, obj=None):
        """已定级评估单冻结：定级是监管依据，改判走新评估单（新一单→重新定级）。"""
        if obj and obj.status == Assessment.Status.CONFIRMED:
            return [
                *self.readonly_fields,
                "resident", "assess_date", "assessor1", "assessor1_emp", "assessor2",
            ]
        return self.readonly_fields

    def _operator(self, request) -> str:
        try:
            return request.user.employee.name
        except Exception:
            return request.user.username

    @action(description="定级确认（按建议档）")
    def action_confirm(self, request, queryset):
        """逐实例 confirm()——queryset.update() 会绕过 StaffFkMixin 与
        CareLevelChange 生成；已定级的报错跳过并计数。"""
        confirmed = skipped = 0
        for a in queryset.select_related("resident"):
            try:
                a.confirm(operator=self._operator(request))
                confirmed += 1
            except ValueError:
                skipped += 1
        self.message_user(request, f"定级 {confirmed} 单（已定级跳过 {skipped} 单）")
