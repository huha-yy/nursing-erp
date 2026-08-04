from django.contrib import admin
from unfold.admin import ModelAdmin
from import_export.admin import ImportExportModelAdmin
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Employee, Schedule, Attendance, Task, Performance


@admin.register(Employee)
class EmployeeAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["name", "dept", "building", "phone", "is_caregiver", "hire_date"]
    list_filter = ["dept", "is_caregiver", "building"]
    search_fields = ["name", "phone"]
    list_per_page = 30


@admin.register(Schedule)
class ScheduleAdmin(BuildingScopeMixin, ModelAdmin):
    building_field = "building"
    list_display = ["employee", "date", "shift", "building", "floor", "task_note"]
    list_filter = ["date", "shift", "building"]
    search_fields = ["employee__name"]
    list_per_page = 50
    date_hierarchy = "date"
    autocomplete_fields = ["employee"]


@admin.register(Attendance)
class AttendanceAdmin(ModelAdmin):
    list_display = ["employee", "date", "clock_in", "clock_out"]
    list_filter = ["date"]
    search_fields = ["employee__name"]
    list_per_page = 50
    date_hierarchy = "date"
    autocomplete_fields = ["employee"]


@admin.register(Task)
class TaskAdmin(BuildingScopeMixin, ModelAdmin):
    building_field = "assignee__building"
    list_display = ["title", "assigner_name", "assignee", "deadline", "is_completed", "created_at"]
    list_filter = ["is_completed", "deadline"]
    search_fields = ["title", "assigner_name", "assignee__name"]
    date_hierarchy = "created_at"
    autocomplete_fields = ["assignee"]


@admin.register(Performance)
class PerformanceAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["employee", "month", "attendance_score", "quality_score", "total_score"]
    list_filter = ["month"]
    search_fields = ["employee__name"]
    autocomplete_fields = ["employee"]
