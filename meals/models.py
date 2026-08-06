from django.db import models


class Dish(models.Model):
    """菜品库 — 食堂维护"""

    class Category(models.TextChoices):
        MEAT = "荤菜", "荤菜"
        VEGETABLE = "素菜", "素菜"
        STAPLE = "主食", "主食"
        SOUP = "汤", "汤"
        SIDE = "小菜", "小菜"
        DRINK = "饮品", "饮品"

    name = models.CharField(max_length=50, verbose_name="菜名")
    category = models.CharField(max_length=10, choices=Category.choices, verbose_name="分类")
    is_available = models.BooleanField(default=True, verbose_name="可用")

    class Meta:
        verbose_name = "菜品库"
        verbose_name_plural = verbose_name
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class WeekMenu(models.Model):
    """每周菜单 — 食堂录入，每天每餐关联可选菜品"""

    class Day(models.TextChoices):
        MON = "周一", "周一"
        TUE = "周二", "周二"
        WED = "周三", "周三"
        THU = "周四", "周四"
        FRI = "周五", "周五"
        SAT = "周六", "周六"
        SUN = "周日", "周日"

    class MealType(models.TextChoices):
        BREAKFAST = "早餐", "早餐"
        LUNCH = "午餐", "午餐"
        DINNER = "晚餐", "晚餐"

    week_start = models.DateField(verbose_name="周一日期")
    day = models.CharField(max_length=4, choices=Day.choices, verbose_name="星期")
    meal_type = models.CharField(max_length=4, choices=MealType.choices, verbose_name="餐次")
    dishes = models.ManyToManyField(Dish, verbose_name="菜品")

    class Meta:
        verbose_name = "周菜单"
        verbose_name_plural = verbose_name
        unique_together = [("week_start", "day", "meal_type")]
        ordering = ["week_start", "day", "meal_type"]

    def __str__(self):
        return f"{self.week_start} {self.get_day_display()} {self.get_meal_type_display()}"


class MealOrder(models.Model):
    """老人点餐 — 护理员从菜单中勾选菜品"""

    class MealType(models.TextChoices):
        BREAKFAST = "早餐", "早餐"
        LUNCH = "午餐", "午餐"
        DINNER = "晚餐", "晚餐"

    class Status(models.TextChoices):
        ORDERED = "ordered", "已点餐"
        MODIFIED = "modified", "已改餐"
        CANCELLED = "cancelled", "已退餐"
        PREPARING = "preparing", "备餐中"
        DELIVERING = "delivering", "送餐中"
        DELIVERED = "delivered", "已送达"

    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="meal_orders",
        verbose_name="老人"
    )
    date = models.DateField(verbose_name="就餐日期")
    meal_type = models.CharField(max_length=4, choices=MealType.choices, verbose_name="餐次")
    dishes = models.ManyToManyField(Dish, verbose_name="所选菜品")
    special_requests = models.CharField(max_length=200, blank=True, verbose_name="特殊需求")
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ORDERED, verbose_name="状态"
    )
    ordered_by = models.CharField(max_length=30, blank=True, verbose_name="点餐人")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "点餐订单"
        verbose_name_plural = verbose_name
        ordering = ["date", "meal_type"]
        indexes = [
            models.Index(fields=["date", "status"]),
            models.Index(fields=["resident", "date"]),
        ]

    def __str__(self):
        dishes_list = ", ".join(self.dishes.values_list("name", flat=True))
        return f"{self.resident.name} — {self.date} {self.get_meal_type_display()}"

    def cancel(self, reason: str = ""):
        self.status = self.Status.CANCELLED
        self.save()
        MealModificationLog.objects.create(order=self, action="cancel", reason=reason)

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


class MealModificationLog(models.Model):
    """改餐/退餐日志"""

    class Action(models.TextChoices):
        MODIFY = "modify", "改餐"
        CANCEL = "cancel", "退餐"

    order = models.ForeignKey(
        MealOrder, on_delete=models.CASCADE, related_name="modifications", verbose_name="订单"
    )
    action = models.CharField(max_length=10, choices=Action.choices, verbose_name="操作类型")
    reason = models.TextField(blank=True, verbose_name="原因")
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.CharField(max_length=30, blank=True, verbose_name="操作人")

    class Meta:
        verbose_name = "改退餐记录"
        verbose_name_plural = verbose_name
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.order} — {self.get_action_display()}"


class MealFinance(models.Model):
    """餐费月结"""
    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="meal_finances",
        verbose_name="老人"
    )
    month = models.CharField(max_length=7, verbose_name="月份")
    total_meals = models.IntegerField(default=0, verbose_name="点餐总数")
    cancelled = models.IntegerField(default=0, verbose_name="退餐次数")
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="应收餐费"
    )
    paid = models.BooleanField(default=False, verbose_name="已缴纳")

    class Meta:
        verbose_name = "餐费月结"
        verbose_name_plural = verbose_name
        unique_together = [("resident", "month")]
        ordering = ["-month", "resident__name"]

    def __str__(self):
        return f"{self.resident.name} — {self.month} ¥{self.amount}"

    @classmethod
    def generate_monthly(cls, resident, month: str, price_per_meal: float = 15):
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
