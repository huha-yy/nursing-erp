from django.contrib import admin
from unfold.admin import ModelAdmin
from import_export.admin import ImportExportModelAdmin

from .models import InventoryItem, StockIn, StockOut, MaintenanceOrder, Inspection, Approval


@admin.register(InventoryItem)
class InventoryItemAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["name", "category", "quantity", "unit", "safety_stock", "low_stock_badge"]
    list_filter = ["category"]
    search_fields = ["name"]
    list_per_page = 30
    actions = ["restock_to_safety"]

    @admin.display(description="库存状态", ordering="quantity")
    def low_stock_badge(self, obj):
        if obj.is_low_stock:
            return f"⚠️ 不足 (仅剩{obj.quantity}{obj.unit})"
        return "✅ 充足"

    @admin.action(description="补货至安全库存")
    def restock_to_safety(self, request, queryset):
        for item in queryset:
            if item.is_low_stock:
                needed = item.safety_stock * 2 - item.quantity
                StockIn.objects.create(
                    item=item, quantity=needed, supplier="系统自动补货",
                    date=timezone.now().date(), operator="管理员"
                )


@admin.register(StockIn)
class StockInAdmin(ModelAdmin):
    list_display = ["item", "quantity", "supplier", "date", "operator"]
    list_filter = ["date", "supplier"]
    search_fields = ["item__name"]
    date_hierarchy = "date"
    autocomplete_fields = ["item"]


@admin.register(StockOut)
class StockOutAdmin(ModelAdmin):
    list_display = ["item", "quantity", "taken_by", "date"]
    list_filter = ["date"]
    search_fields = ["item__name", "taken_by"]
    date_hierarchy = "date"
    autocomplete_fields = ["item"]


@admin.register(MaintenanceOrder)
class MaintenanceOrderAdmin(ModelAdmin):
    list_display = ["equipment_name", "location", "status", "reported_by", "reported_at"]
    list_filter = ["status"]
    search_fields = ["equipment_name", "location", "fault_description"]
    date_hierarchy = "reported_at"
    actions = ["mark_in_progress", "mark_done"]

    @admin.action(description="标记为维修中")
    def mark_in_progress(self, request, queryset):
        queryset.filter(status="pending").update(status="in_progress")

    @admin.action(description="标记为已完成")
    def mark_done(self, request, queryset):
        from django.utils import timezone
        queryset.filter(status__in=["pending", "in_progress"]).update(
            status="done", resolved_at=timezone.now()
        )


@admin.register(Inspection)
class InspectionAdmin(ModelAdmin, ImportExportModelAdmin):
    list_display = ["area", "inspector_name", "date", "result", "note_short"]
    list_filter = ["result", "date"]
    search_fields = ["area", "inspector_name"]
    date_hierarchy = "date"

    @admin.display(description="备注")
    def note_short(self, obj):
        return obj.note[:40] + "…" if len(obj.note) > 40 else obj.note


@admin.register(Approval)
class ApprovalAdmin(ModelAdmin):
    list_display = ["title", "applicant_name", "approval_type", "status", "created_at"]
    list_filter = ["approval_type", "status"]
    search_fields = ["title", "applicant_name", "content"]
    date_hierarchy = "created_at"
    actions = ["approve_selected", "reject_selected"]

    @admin.action(description="批量通过")
    def approve_selected(self, request, queryset):
        queryset.filter(status="pending").update(status="approved")

    @admin.action(description="批量驳回")
    def reject_selected(self, request, queryset):
        queryset.filter(status="pending").update(status="rejected")


# timezone import for inventory restock action
from django.utils import timezone
