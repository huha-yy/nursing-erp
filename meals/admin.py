import re
from datetime import date, timedelta

from django.contrib import admin
from django.db.models import Case, IntegerField, When
from django.shortcuts import redirect
from unfold.admin import ModelAdmin
from unfold.decorators import action

from nursing_erp.admin_mixins import BuildingScopeMixin

from .models import Dish, MealFinance, MealModificationLog, MealOrder, WeekMenu


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# 汉字码点序是乱的（一三二五四六日），排序必须映射成数字；
# Meta.ordering 不支持表达式，故在 ModelAdmin.ordering 上声明
_DAY_ORDER = Case(
    *[When(day=v, then=i) for i, v in enumerate(WeekMenu.Day.values, 1)],
    output_field=IntegerField(),
)
_MEAL_ORDER = Case(
    *[When(meal_type=v, then=i) for i, v in enumerate(WeekMenu.MealType.values, 1)],
    output_field=IntegerField(),
)


class WeekOfFilter(admin.SimpleListFilter):
    """按周筛选：候选 = 库里有菜单的最近 12 周（本周/上周打标），选中即锁定。"""

    title = "周"
    parameter_name = "week"

    def lookups(self, request, model_admin):
        this_monday = _monday(date.today())
        tags = {
            this_monday: "（本周）",
            this_monday - timedelta(days=7): "（上周）",
        }
        return [
            (ws.isoformat(),
             f"{ws:%m-%d} ~ {(ws + timedelta(days=6)):%m-%d}{tags.get(ws, '')}")
            for ws in (WeekMenu.objects.order_by("-week_start")
                       .values_list("week_start", flat=True).distinct()[:12])
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(week_start=self.value())
        return queryset


@admin.register(Dish)
class DishAdmin(ModelAdmin):
    list_display = ["name", "category", "is_available"]
    list_filter = ["category", "is_available"]
    search_fields = ["name"]
    list_per_page = 50


_DATE_Q_RE = re.compile(r"^\s*(\d{4})[-/.年]?(\d{1,2})[-/.月]?(\d{1,2})日?\s*$")


@admin.register(WeekMenu)
class WeekMenuAdmin(ModelAdmin):
    list_display = ["week_start", "day", "meal_type", "dishes_list"]
    list_filter = [WeekOfFilter, "day", "meal_type"]
    search_fields = ["dishes__name"]
    search_help_text = "菜品名，或该周任一日期（2026-08-24 / 8/24 / 2026年8月24日）→ 查当周菜单"
    list_per_page = 30
    filter_horizontal = ["dishes"]
    ordering = ["week_start", _DAY_ORDER, _MEAL_ORDER]

    def get_search_results(self, request, queryset, search_term):
        """搜索框输入该周任意一天 → 直接锁定那一周（与已选周筛选取交集）。"""
        m = _DATE_Q_RE.match(search_term)
        if m:
            try:
                d = date(int(m[1]), int(m[2]), int(m[3]))
            except ValueError:  # 2026-13-40 之类非法日期 → 回退普通菜品搜索
                pass
            else:
                return queryset.filter(week_start=_monday(d)), False
        return super().get_search_results(request, queryset, search_term)

    def changelist_view(self, request, extra_context=None):
        # 无任何筛选条件时默认聚焦本周（打开即看本周菜单，而不是最早一周）
        if request.method == "GET" and not set(request.GET) & {"week", "q", "day", "meal_type"}:
            monday = _monday(date.today())
            if WeekMenu.objects.filter(week_start=monday).exists():
                return redirect(f"{request.path}?week={monday.isoformat()}")
        return super().changelist_view(request, extra_context)

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
    autocomplete_fields = ["resident", "ordered_by_emp"]
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
    autocomplete_fields = ["changed_by_emp"]
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
