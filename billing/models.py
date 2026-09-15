"""应收月账单 — Q3 定稿（2026-08-21）：床位费+护理费+餐费合并出账。

核心口径：
- 整月计费：床位/护理按自然月全额，不按入住/离院分摊（生产 36 位老人
  admission_date 全空、36 房全单床，按天分摊显式延后至有数据时）
- 餐费以 MealFinance 为唯一数据源；当月无点餐不造 0 元月结行
  （老 /finance/ 页与 /api/meal-finance/ 数据面零变化，meals/ 不改）
- 已缴费账单金额冻结：再生成直接跳过；撤销核销→再生成→再核销是修正流程
- 价目缺行 fail-loud（FeeRuleMissing），批量生成包 transaction.atomic 整批回滚
"""

from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from meals.models import MealFinance, MealOrder
from nursing_erp.staff_fk import StaffFkMixin


class FeeRuleMissing(LookupError):  # noqa: N818 — 仿 Django DoesNotExist 家族命名
    """价目表缺行 — fail-loud：管理员须先在后台「价目表」补配置再出账。"""


class FeeRule(models.Model):
    """价目表 — 后台可改，出账时实时读取（不缓存）。"""

    class FeeType(models.TextChoices):
        BED = "bed", _("床位费")
        NURSING = "nursing", _("护理费")
        MEAL = "meal", _("餐费")

    fee_type = models.CharField(max_length=10, choices=FeeType.choices, verbose_name=_("费用类型"))
    key = models.CharField(
        max_length=20, blank=True, default="", verbose_name=_("档位"),
        help_text=_("护理费=护理等级（自理/半护/全护/失智）；床位费/餐费留空"),
    )
    monthly_amount = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name=_("单价(元)"),
        help_text=_("床位/护理=每月；餐费=每餐"),
    )

    class Meta:
        verbose_name = _("价目表")
        verbose_name_plural = _("价目表")
        ordering = ["fee_type", "key"]
        constraints = [
            models.UniqueConstraint(fields=["fee_type", "key"], name="feerule_type_key_unique"),
        ]

    def __str__(self):
        label = self.get_fee_type_display()
        if self.key:
            return f"{label}·{self.key} ¥{self.monthly_amount}"
        return f"{label} ¥{self.monthly_amount}"

    @classmethod
    def get_amount(cls, fee_type: str, key: str = "") -> Decimal:
        rule = cls.objects.filter(fee_type=fee_type, key=key).first()
        if rule is None:
            raise FeeRuleMissing(
                _("价目表缺行：{} 档位={} —— 请先在后台「价目表」补配置再出账").format(
                    fee_type, key or "（空）"
                )
            )
        return rule.monthly_amount

    @classmethod
    def get_bed_fee(cls) -> Decimal:
        return cls.get_amount(cls.FeeType.BED)

    @classmethod
    def get_nursing_fee(cls, care_level: str) -> Decimal:
        return cls.get_amount(cls.FeeType.NURSING, care_level)

    @classmethod
    def get_meal_price(cls) -> Decimal:
        return cls.get_amount(cls.FeeType.MEAL)


class MonthlyBill(StaffFkMixin, models.Model):
    """应收月账单 — 一人一账期一张单，整月计费。

    金额全链 Decimal（价目非整数时的 float 尾尘防线）。
    注意：queryset.update()/bulk_update 绕过 save() 的 total 重算与
    StaffFkMixin —— 核销/减免一律逐条 save()/settle()。
    """

    staff_fk_fields = (("settled_by", "settled_by_emp"),)

    class Status(models.TextChoices):
        PENDING = "pending", _("待缴费")
        PAID = "paid", _("已缴费")

    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="bills", verbose_name=_("老人")
    )
    month = models.CharField(max_length=7, verbose_name=_("账期"))
    bed_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("床位费"))
    nursing_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name=_("护理费")
    )
    meal_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("餐费"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name=_("合计"))
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, verbose_name=_("状态")
    )
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name=_("核销时间"))
    settled_by = models.CharField(max_length=30, blank=True, verbose_name=_("核销人"))
    settled_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="settled_bills", verbose_name=_("核销人档案"),
    )
    note = models.CharField(max_length=200, blank=True, verbose_name=_("备注（减免等）"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("应收月账单")
        verbose_name_plural = verbose_name
        ordering = ["-month", "resident__name"]
        unique_together = [("resident", "month")]
        indexes = [models.Index(fields=["month", "status"])]

    def __str__(self):
        return f"{self.resident.name} {self.month} ¥{self.total}"

    def save(self, *args, **kwargs):
        """合计 = 三费之和（admin 手工减免后保存即重算）。

        Decimal() 包一层：create(bed_fee=800) 这类 int/str 入参不会让
        int + Decimal 退化成 int 而 quantize 崩溃。
        """
        self.total = (
            Decimal(self.bed_fee) + Decimal(self.nursing_fee) + Decimal(self.meal_fee)
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def settle(self, operator: str = "", note: str = "") -> None:
        """全额核销（幂等：已 paid 直接返回）。operator 触发 StaffFkMixin 自动挂档案。"""
        if self.status == self.Status.PAID:
            return
        self.status = self.Status.PAID
        self.settled_at = timezone.now()
        if operator:
            self.settled_by = operator
        if note:
            self.note = note
        self.save()

    def unsettle(self) -> None:
        """撤销核销（幂等）——回 pending、清核销痕迹；金额不动，再生成时刷新。"""
        if self.status == self.Status.PENDING:
            return
        self.status = self.Status.PENDING
        self.settled_at = None
        self.settled_by = ""
        self.settled_by_emp = None
        self.save()

    @classmethod
    def generate_month(cls, resident, month: str) -> "MonthlyBill":
        """生成/刷新一位老人的月账单（幂等；已缴费冻结原样返回）。

        - 在住（bed 非空）→ 床位/护理按价目整月全额；非在住 → 双 0（收尾账单）
        - 当月有点餐 → 先刷新 MealFinance 月结行（价目单价以 Decimal 传入，防
          float 尾尘）再取 amount；无点餐 → 读已有月结行，无行则 0，不造幽灵行
        - 价目缺行 raise FeeRuleMissing（批量侧包 atomic 整批回滚）
        """
        existing = cls.objects.filter(resident=resident, month=month).first()
        if existing and existing.status == cls.Status.PAID:
            return existing  # 已缴费冻结

        in_residence = resident.bed_id is not None
        bed_fee = FeeRule.get_bed_fee() if in_residence else Decimal("0")
        nursing_fee = (
            FeeRule.get_nursing_fee(resident.care_level) if in_residence else Decimal("0")
        )

        has_orders = MealOrder.objects.filter(
            resident=resident, date__startswith=month
        ).exists()
        if has_orders:
            MealFinance.generate_monthly(resident, month, price_per_meal=FeeRule.get_meal_price())
        finance = MealFinance.objects.filter(resident=resident, month=month).first()
        meal_fee = finance.amount if finance else Decimal("0")

        bill, _ = cls.objects.update_or_create(
            resident=resident,
            month=month,
            defaults={"bed_fee": bed_fee, "nursing_fee": nursing_fee, "meal_fee": meal_fee},
        )
        return bill
