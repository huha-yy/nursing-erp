from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import action
from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Dish, WeekMenu, MealOrder, MealModificationLog, MealFinance


@admin.register(Dish)
class DishAdmin(ModelAdmin):
    list_display = ["name", "category", "is_available"]
    list_filter = ["category", "is_available"]
    search_fields = ["name"]
    list_per_page = 50


@admin.register(WeekMenu)
class WeekMenuAdmin(ModelAdmin):
    list_display = ["week_start", "day", "meal_type", "dishes_list"]
    list_filter = ["week_start", "day", "meal_type"]
    search_fields = ["dishes__name"]
    list_per_page = 30
    filter_horizontal = ["dishes"]

    @admin.display(description="菜品")
    def dishes_list(self, obj):
        return ", ".join(obj.dishes.values_list("name", flat=True))


@admin.register(MealOrder)
class MealOrderAdmin(BuildingScopeMixin, ModelAdmin):
    building_field = "resident__building"
    list_display = ["resident", "date", "meal_type", "dishes_short", "special_requests",
                    "status_badge", "ordered_by", "created_at"]
    list_filter = ["status", "meal_type", "date"]
    search_fields = ["resident__name", "dishes__name"]
    list_per_page = 50
    date_hierarchy = "date"
    autocomplete_fields = ["resident"]
    filter_horizontal = ["dishes"]
    actions = ["action_cancel", "action_preparing", "action_delivering", "action_delivered"]

    @admin.display(description="菜品")
    def dishes_short(self, obj):
        names = ", ".join(obj.dishes.values_list("name", flat=True))
        return names[:50] + "…" if len(names) > 50 else names

    @admin.display(description="状态")
    def status_badge(self, obj):
        return obj.get_status_display()

    @action(description="退餐")
    def action_cancel(self, request, queryset):
        for o in queryset.filter(status__in=["ordered", "modified"]):
            o.cancel("管理员操作退餐")

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
