from django.contrib import admin
from unfold.admin import ModelAdmin
from import_export.admin import ImportExportModelAdmin
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Resident, NursingLog, HealthRecord, MedicationRecord, ResidentRoutine, CareLevelChange, TransferRecord, DischargeRecord
from incidents.models import IncidentReport


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
    list_display = ["name", "gender", "age", "building", "floor", "room",
                    "care_level", "contact_name", "contact_phone", "lifecycle_link"]
    list_filter = ["building", "floor", "care_level", "gender"]
    search_fields = ["name", "id_card", "diagnosis"]
    list_per_page = 30
    inlines = [
        NursingLogInline,
        HealthRecordInline,
        MedicationRecordInline,
        ResidentRoutineInline,
        IncidentReportInline,
        CareLevelChangeInline,
        TransferRecordInline,
        DischargeRecordInline,
    ]
    fieldsets = (
        ("基本信息", {"fields": ("name", "gender", "age", "id_card", "photo")}),
        ("入住信息", {"fields": ("building", "floor", "room", "admission_date")}),
        ("健康档案", {"fields": ("care_level", "diagnosis", "allergies")}),
        ("家属信息", {"fields": ("contact_name", "contact_phone")}),
        ("其他", {"fields": ("notes",)}),
    )

    @admin.display(description="生命周期")
    def lifecycle_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        return format_html(
            '<a href="{}" style="color:#4f6ef7;font-weight:600;display:inline-flex;align-items:center;gap:5px">'
            '<span class="material-symbols-outlined" style="font-size:16px">visibility</span>查看</a>',
            reverse("resident_lifecycle", args=[obj.id]),
        )


@admin.register(NursingLog)
class NursingLogAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "log_date", "category", "staff_name", "detail_short"]
    list_filter = ["category", "log_date"]
    search_fields = ["resident__name", "detail"]
    list_per_page = 30
    date_hierarchy = "log_date"
    autocomplete_fields = ["resident"]

    @admin.display(description="摘要")
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
    autocomplete_fields = ["resident"]


@admin.register(TransferRecord)
class TransferRecordAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "from_zone", "to_zone", "transfer_date"]
    list_filter = ["transfer_date"]
    search_fields = ["resident__name"]
    date_hierarchy = "transfer_date"
    autocomplete_fields = ["resident"]


@admin.register(DischargeRecord)
class DischargeRecordAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "discharge_type", "discharge_date"]
    list_filter = ["discharge_type", "discharge_date"]
    search_fields = ["resident__name"]
    date_hierarchy = "discharge_date"
    autocomplete_fields = ["resident"]
