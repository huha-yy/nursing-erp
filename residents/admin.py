from django.contrib import admin
from unfold.admin import ModelAdmin
from import_export.admin import ImportExportModelAdmin
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Resident, NursingLog, HealthRecord, MedicationRecord, ResidentRoutine


@admin.register(Resident)
class ResidentAdmin(BuildingScopeMixin, ModelAdmin, ImportExportModelAdmin):
    building_field = "building"
    list_display = ["name", "gender", "age", "building", "floor", "room",
                    "care_level", "contact_name", "contact_phone"]
    list_filter = ["building", "floor", "care_level", "gender"]
    search_fields = ["name", "id_card", "diagnosis"]
    list_per_page = 30
    fieldsets = (
        ("基本信息", {"fields": ("name", "gender", "age", "id_card", "photo")}),
        ("入住信息", {"fields": ("building", "floor", "room", "admission_date")}),
        ("健康档案", {"fields": ("care_level", "diagnosis", "allergies")}),
        ("家属信息", {"fields": ("contact_name", "contact_phone")}),
        ("其他", {"fields": ("notes",)}),
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
