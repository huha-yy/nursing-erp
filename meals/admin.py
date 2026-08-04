from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import action
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import MealPlan, MealOrder, MealModificationLog, MealFinance


@admin.register(MealPlan)
class MealPlanAdmin(ModelAdmin):
    list_display = ["date", "meal_type", "menu_short"]
    list_filter = ["meal_type", "date"]
    date_hierarchy = "date"

    @admin.display(description="菜品")
    def menu_short(self, obj):
        return obj.menu_items[:60] + "…" if len(obj.menu_items) > 60 else obj.menu_items


@admin.register(MealOrder)
class MealOrderAdmin(BuildingScopeMixin, ModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "date", "meal_type", "status_badge",
                    "special_requests_short", "ordered_by", "created_at"]
    list_filter = ["status", "meal_type", "date"]
    search_fields = ["resident__name", "menu_choice"]
    list_per_page = 50
    date_hierarchy = "date"
    autocomplete_fields = ["resident"]
    actions = ["action_preparing", "action_delivering", "action_delivered"]

    @admin.display(description="状态")
    def status_badge(self, obj):
        return obj.get_status_display()

    @admin.display(description="特殊要求")
    def special_requests_short(self, obj):
        if not obj.special_requests:
            return "-"
        return obj.special_requests[:30] + "…" if len(obj.special_requests) > 30 else obj.special_requests

    @action(description="批量设为备餐中")
    def action_preparing(self, request, queryset):
        queryset.filter(status="ordered").update(status="preparing")

    @action(description="批量设为送餐中")
    def action_delivering(self, request, queryset):
        queryset.filter(status="preparing").update(status="delivering")

    @action(description="批量设为已送达")
    def action_delivered(self, request, queryset):
        queryset.filter(status="delivering").update(status="delivered")


@admin.register(MealModificationLog)
class MealModificationLogAdmin(ModelAdmin):
    list_display = ["order_info", "action", "reason_short", "changed_at", "changed_by"]
    list_filter = ["action", "changed_at"]
    date_hierarchy = "changed_at"

    @admin.display(description="订单")
    def order_info(self, obj):
        return str(obj.order)

    @admin.display(description="原因")
    def reason_short(self, obj):
        return obj.reason[:60] + "…" if len(obj.reason) > 60 else obj.reason


@admin.register(MealFinance)
class MealFinanceAdmin(BuildingScopeMixin, ModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "month", "total_meals", "cancelled", "amount", "paid"]
    list_filter = ["month", "paid"]
    search_fields = ["resident__name"]
    actions = ["action_mark_paid"]

    @action(description="标记为已缴纳")
    def action_mark_paid(self, request, queryset):
        queryset.update(paid=True)
