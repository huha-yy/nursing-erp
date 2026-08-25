from django.contrib import admin
from django.contrib.admin.models import LogEntry
from import_export.admin import ExportActionModelAdmin

from .models import OperationLog


@admin.register(OperationLog)
class OperationLogAdmin(ExportActionModelAdmin):
    """操作日志——只读审计视图：筛选/搜索/导出，不可增删改（保完整性）。

    ExportActionModelAdmin 提供 changelist 勾选导出 CSV/Excel（import_export
    已装）；字段全 readonly，审计日志不容手改。
    """

    list_display = ("created_at", "actor_name", "actor_badge", "action",
                    "target", "status_code", "path")
    list_filter = ("actor_type", "action", "created_at")
    search_fields = ("actor_name", "target", "detail", "path")
    date_hierarchy = "created_at"
    list_per_page = 50

    @admin.display(description="身份", ordering="actor_type")
    def actor_badge(self, obj):
        return obj.get_actor_type_display()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # 只读：详情页可看不可改

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LogEntry)
class DjangoLogEntryAdmin(admin.ModelAdmin):
    """Django 自带后台操作日志（admin 台账增删改）——挂出来可查。

    与 OperationLog 互补：这张表只覆盖 /admin/ 台账操作，API/页面/AI
    写操作在 OperationLog。
    """

    list_display = ("action_time", "user", "action_flag", "object_repr", "change_message")
    list_filter = ("user", "action_flag", "action_time")
    search_fields = ("object_repr", "change_message", "user__username")
    date_hierarchy = "action_time"
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
