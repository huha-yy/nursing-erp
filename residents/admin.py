from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from import_export.admin import ImportExportModelAdmin
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import (AdmissionRecord, CareLevelChange, DischargeRecord, HealthRecord,
                     MedicationRecord, NursingLog, Resident, ResidentRoutine, TransferRecord)
from assessments.models import Assessment
from incidents.models import IncidentReport


def _text_short(text, limit=20):
    """列表页长文本截断（离院/转区原因等）；空值显示占位符。"""
    text = (text or "").strip()
    if not text:
        return "—"
    return text[:limit] + "…" if len(text) > limit else text


class NursingLogInline(admin.TabularInline):
    model = NursingLog
    extra = 0
    fields = ("log_date", "category", "staff_name", "detail")
    ordering = ("-log_date",)


class HealthRecordInline(admin.TabularInline):
    model = HealthRecord
    extra = 0
    fields = ("record_date", "blood_pressure", "blood_sugar", "heart_rate", "weight", "temperature")
    ordering = ("-record_date",)


class MedicationRecordInline(admin.TabularInline):
    model = MedicationRecord
    extra = 0
    fields = ("medicine_name", "dosage", "frequency", "start_date", "end_date", "is_active")
    ordering = ("-start_date",)


class ResidentRoutineInline(admin.TabularInline):
    model = ResidentRoutine
    extra = 0
    fields = ("log_date", "wake_up", "sleep", "breakfast", "lunch", "dinner", "mood")
    ordering = ("-log_date",)


class IncidentReportInline(admin.TabularInline):
    model = IncidentReport
    extra = 0
    fields = ("category", "severity", "handled", "handled_by", "description")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)


class CareLevelChangeInline(admin.TabularInline):
    model = CareLevelChange
    extra = 0
    fields = ("change_date", "from_level", "to_level", "reason", "changed_by")
    ordering = ("-change_date",)


class AssessmentInline(admin.TabularInline):
    """评估单查阅入口——建单/定级走 /assessments/ 看板或评估记录 admin。"""
    model = Assessment
    extra = 0
    fields = ("assess_date", "total_score", "suggested_level", "status", "final_level")
    ordering = ("-assess_date",)
    show_change_link = True


class TransferRecordInline(admin.TabularInline):
    model = TransferRecord
    extra = 0
    fields = ("transfer_date", "from_zone", "to_zone", "reason")
    ordering = ("-transfer_date",)


class DischargeRecordInline(admin.TabularInline):
    model = DischargeRecord
    extra = 0
    fields = ("discharge_date", "discharge_type", "reason")
    ordering = ("-discharge_date",)


@admin.register(Resident)
class ResidentAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "building"
    list_display = ["name", "gender", "age", "building", "floor", "room", "admission_date",
                    "care_level", "contact_name", "contact_phone", "lifecycle_link"]
    list_filter = ["building", "floor", "care_level", "gender"]
    search_fields = ["name", "id_card", "diagnosis"]
    autocomplete_fields = ["bed"]
    list_per_page = 30
    inlines = [
        NursingLogInline,
        HealthRecordInline,
        MedicationRecordInline,
        ResidentRoutineInline,
        IncidentReportInline,
        CareLevelChangeInline,
        AssessmentInline,
        TransferRecordInline,
        DischargeRecordInline,
    ]
    fieldsets = (
        (_("基本信息"), {"fields": ("name", "gender", "age", "id_card", "photo")}),
        # 床位是权威数据源：选床后楼栋/楼层/房间自动同步（以床位为准）。
        # 字符串列保持可编辑，兼容"台账未建链先收人"与脚本导入的过渡期。
        (_("入住信息"), {"fields": ("bed", "admission_date", "building", "floor", "room")}),
        (_("健康档案"), {"fields": ("care_level", "diagnosis", "allergies")}),
        (_("家属信息"), {"fields": ("contact_name", "contact_phone")}),
        (_("其他"), {"fields": ("notes",)}),
    )

    @admin.display(description=_("生命周期"))
    def lifecycle_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        return format_html(
            '<a href="{}" style="color:#4f6ef7;font-weight:600;display:inline-flex;align-items:center;gap:5px">'
            '<span class="material-symbols-outlined" style="font-size:16px">visibility</span>{}</a>',
            reverse("resident_lifecycle", args=[obj.id]),
            _("查看"),
        )


@admin.register(NursingLog)
class NursingLogAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "log_date", "category", "staff_name", "detail_short"]
    list_filter = ["category", "log_date"]
    search_fields = ["resident__name", "detail"]
    list_per_page = 30
    date_hierarchy = "log_date"
    autocomplete_fields = ["resident", "staff_emp"]

    @admin.display(description=_("摘要"))
    def detail_short(self, obj):
        return obj.detail[:50] + "…" if len(obj.detail) > 50 else obj.detail


@admin.register(HealthRecord)
class HealthRecordAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "record_date", "blood_pressure", "blood_sugar",
                    "heart_rate", "weight", "temperature"]
    list_filter = ["record_date"]
    search_fields = ["resident__name"]
    list_per_page = 30
    date_hierarchy = "record_date"
    autocomplete_fields = ["resident"]


@admin.register(MedicationRecord)
class MedicationRecordAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "medicine_name", "dosage", "frequency",
                    "start_date", "end_date", "is_active"]
    list_filter = ["is_active", "frequency"]
    search_fields = ["resident__name", "medicine_name"]
    list_per_page = 30
    autocomplete_fields = ["resident"]


@admin.register(ResidentRoutine)
class ResidentRoutineAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "log_date", "wake_up", "sleep", "breakfast",
                    "lunch", "dinner", "mood"]
    list_filter = ["log_date"]
    search_fields = ["resident__name"]
    date_hierarchy = "log_date"
    autocomplete_fields = ["resident"]


@admin.register(CareLevelChange)
class CareLevelChangeAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "from_level", "to_level", "change_date", "changed_by"]
    list_filter = ["change_date", "to_level"]
    search_fields = ["resident__name"]
    date_hierarchy = "change_date"
    autocomplete_fields = ["resident", "changed_by_emp"]
    readonly_fields = ["assessment"]  # 定级自动回填的关联，后台不可手改


@admin.register(TransferRecord)
class TransferRecordAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "from_zone", "to_zone", "transfer_date",
                    "resident_building", "reason_short"]
    list_filter = ["resident__building", "transfer_date"]
    search_fields = ["resident__name"]
    date_hierarchy = "transfer_date"
    autocomplete_fields = ["resident"]

    @admin.display(description=_("楼栋"))
    def resident_building(self, obj):
        return obj.resident.building

    @admin.display(description=_("原因"))
    def reason_short(self, obj):
        return _text_short(obj.reason)


@admin.register(DischargeRecord)
class DischargeRecordAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "discharge_type", "discharge_date",
                    "resident_building", "reason_short"]
    list_filter = ["discharge_type", "resident__building", "discharge_date"]
    search_fields = ["resident__name"]
    date_hierarchy = "discharge_date"
    autocomplete_fields = ["resident"]

    @admin.display(description=_("楼栋"))
    def resident_building(self, obj):
        return obj.resident.building

    @admin.display(description=_("原因"))
    def reason_short(self, obj):
        return _text_short(obj.reason)


@admin.register(AdmissionRecord)
class AdmissionRecordAdmin(BuildingScopeMixin, ModelAdmin):
    """入住记录 — 只读台账（入院 = 建档挂床；新增入院走老人档案）。

    view-only：有 view 权限可看列表与只读详情；增删改一律关死，
    防止与老人档案形成两个写入入口。
    """

    building_field = "building"
    list_display = ["admission_date", "name", "gender", "age",
                    "building", "floor", "room", "care_level"]
    list_filter = ["building", "care_level"]
    search_fields = ["name", "id_card"]
    date_hierarchy = "admission_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
