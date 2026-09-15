from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from nursing_erp.staff_fk import StaffFkMixin


class Dish(models.Model):
    """菜品库 — 食堂维护"""

    class Category(models.TextChoices):
        MEAT = "荤菜", _("荤菜")
        VEGETABLE = "素菜", _("素菜")
        STAPLE = "主食", _("主食")
        SOUP = "汤", _("汤")
        SIDE = "小菜", _("小菜")
        DRINK = "饮品", _("饮品")

    name = models.CharField(max_length=50, verbose_name=_("菜名"))
    category = models.CharField(max_length=10, choices=Category.choices, verbose_name=_("分类"))
    is_available = models.BooleanField(default=True, verbose_name=_("可用"))

    class Meta:
        verbose_name = _("菜品库")
        verbose_name_plural = verbose_name
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class WeekMenu(models.Model):
    """每周菜单 — 食堂录入，每天每餐关联可选菜品"""

    class Day(models.TextChoices):
        MON = "周一", _("周一")
        TUE = "周二", _("周二")
        WED = "周三", _("周三")
        THU = "周四", _("周四")
        FRI = "周五", _("周五")
        SAT = "周六", _("周六")
        SUN = "周日", _("周日")

    class MealType(models.TextChoices):
        BREAKFAST = "早餐", _("早餐")
        LUNCH = "午餐", _("午餐")
        DINNER = "晚餐", _("晚餐")

    week_start = models.DateField(verbose_name=_("周一日期"))
    day = models.CharField(max_length=4, choices=Day.choices, verbose_name=_("星期"))
    meal_type = models.CharField(max_length=4, choices=MealType.choices, verbose_name=_("餐次"))
    dishes = models.ManyToManyField(Dish, verbose_name=_("菜品"))

    class Meta:
        verbose_name = _("周菜单")
        verbose_name_plural = verbose_name
        unique_together = [("week_start", "day", "meal_type")]
        ordering = ["week_start", "day", "meal_type"]

    def __str__(self):
        return f"{self.week_start} {self.get_day_display()} {self.get_meal_type_display()}"


class MealOrder(StaffFkMixin, models.Model):
    """老人点餐 — 护理员从菜单中勾选菜品"""

    staff_fk_fields = (("ordered_by", "ordered_by_emp"),)

    class MealType(models.TextChoices):
        BREAKFAST = "早餐", _("早餐")
        LUNCH = "午餐", _("午餐")
        DINNER = "晚餐", _("晚餐")

    class Status(models.TextChoices):
        ORDERED = "ordered", _("已点餐")
        MODIFIED = "modified", _("已改餐")
        CANCELLED = "cancelled", _("已退餐")
        PREPARING = "preparing", _("备餐中")
        DELIVERING = "delivering", _("送餐中")
        DELIVERED = "delivered", _("已送达")

    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="meal_orders",
        verbose_name=_("老人")
    )
    date = models.DateField(verbose_name=_("就餐日期"))
    meal_type = models.CharField(max_length=4, choices=MealType.choices, verbose_name=_("餐次"))
    dishes = models.ManyToManyField(Dish, verbose_name=_("所选菜品"))
    special_requests = models.CharField(max_length=200, blank=True, verbose_name=_("特殊需求"))
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ORDERED, verbose_name=_("状态")
    )
    ordered_by = models.CharField(max_length=30, blank=True, verbose_name=_("点餐人"))
    ordered_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="meal_orders", verbose_name=_("点餐人档案"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("点餐订单")
        verbose_name_plural = verbose_name
        ordering = ["date", "meal_type"]
        indexes = [
            models.Index(fields=["date", "status"]),
            models.Index(fields=["resident", "date"]),
        ]
        constraints = [
            # 同一老人同一日期同一餐次只允许一张有效订单（已退餐除外，
            # 退餐后可重新点餐）。背景：OCR 重复识别曾给张国栋造出
            # 171 条同周重复点餐，直接抬高月结餐费与应收账单。
            models.UniqueConstraint(
                fields=["resident", "date", "meal_type"],
                condition=~models.Q(status="cancelled"),
                name="uniq_active_meal_order_per_slot",
            ),
        ]

    def __str__(self):
        dishes_list = ", ".join(self.dishes.values_list("name", flat=True))
        return f"{self.resident.name} — {self.date} {self.get_meal_type_display()}"

    def cancel(self, reason: str = "", operator: str = ""):
        """退餐并留痕。operator 记操作人（家属代退时传"家属-王丽华（子女）"），
        员工端现有调用不传参，行为与历史一致（changed_by 落空串）。"""
        self.status = self.Status.CANCELLED
        self.save()
        MealModificationLog.objects.create(
            order=self, action="cancel", reason=reason, changed_by=operator
        )

    def modify_dishes(self, dish_ids: list[int], reason: str = ""):
        old_names = ", ".join(self.dishes.values_list("name", flat=True))
        self.dishes.set(dish_ids)
        self.status = self.Status.MODIFIED
        self.save()
        new_names = ", ".join(self.dishes.values_list("name", flat=True))
        MealModificationLog.objects.create(
            order=self, action="modify",
            reason=f"原: {old_names} → 新: {new_names}" + (f" ({reason})" if reason else "")
        )


class MealModificationLog(StaffFkMixin, models.Model):
    """改餐/退餐日志"""

    staff_fk_fields = (("changed_by", "changed_by_emp"),)

    class Action(models.TextChoices):
        MODIFY = "modify", _("改餐")
        CANCEL = "cancel", _("退餐")

    order = models.ForeignKey(
        MealOrder, on_delete=models.CASCADE, related_name="modifications", verbose_name=_("订单")
    )
    action = models.CharField(max_length=10, choices=Action.choices, verbose_name=_("操作类型"))
    reason = models.TextField(blank=True, verbose_name=_("原因"))
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.CharField(max_length=30, blank=True, verbose_name=_("操作人"))
    changed_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="meal_modifications", verbose_name=_("操作人档案"),
    )

    class Meta:
        verbose_name = _("改退餐记录")
        verbose_name_plural = verbose_name
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.order} — {self.get_action_display()}"


class MealFinance(models.Model):
    """餐费月结"""
    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="meal_finances",
        verbose_name=_("老人")
    )
    month = models.CharField(max_length=7, verbose_name=_("月份"))
    total_meals = models.IntegerField(default=0, verbose_name=_("点餐总数"))
    cancelled = models.IntegerField(default=0, verbose_name=_("退餐次数"))
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name=_("应收餐费")
    )
    paid = models.BooleanField(default=False, verbose_name=_("已缴纳"))

    class Meta:
        verbose_name = _("餐费月结")
        verbose_name_plural = verbose_name
        unique_together = [("resident", "month")]
        ordering = ["-month", "resident__name"]

    def __str__(self):
        return f"{self.resident.name} — {self.month} ¥{self.amount}"

    @classmethod
    def generate_monthly(cls, resident, month: str, price_per_meal: Decimal | float):
        """生成/刷新月结行（update_or_create 幂等）。

        单价由调用方显式传入——真源是 billing.FeeRule.get_meal_price()。
        不设默认值：防止新调用点悄悄回落到硬编码 15 元。
        """
        orders = MealOrder.objects.filter(resident=resident, date__startswith=month)
        total = orders.count()
        cancelled_count = orders.filter(status="cancelled").count()
        effective = total - cancelled_count
        obj, _ = cls.objects.update_or_create(
            resident=resident, month=month,
            defaults={
                "total_meals": total,
                "cancelled": cancelled_count,
                "amount": effective * price_per_meal,
            }
        )
        return obj
