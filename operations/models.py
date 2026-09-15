from django.db import models
from django.utils.translation import gettext_lazy as _

from nursing_erp.staff_fk import StaffFkMixin


class InventoryItem(models.Model):
    """库存台账（InventoryItem）"""

    class Category(models.TextChoices):
        CONSUMABLE = "护理耗材", _("护理耗材")
        MEDICAL = "医疗器械", _("医疗器械")
        PROTECTIVE = "防护用品", _("防护用品")
        CLEANING = "清洁消毒", _("清洁消毒")
        ASSISTIVE = "辅助器具", _("辅助器具")

    name = models.CharField(max_length=100, verbose_name=_("物品名称"))
    category = models.CharField(max_length=10, choices=Category.choices, verbose_name=_("分类"))
    quantity = models.IntegerField(default=0, verbose_name=_("库存数量"))
    unit = models.CharField(max_length=10, verbose_name=_("单位"))
    safety_stock = models.IntegerField(default=10, verbose_name=_("安全库存"))

    class Meta:
        verbose_name = _("库存台账")
        verbose_name_plural = verbose_name
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} ({self.quantity}{self.unit})"

    @property
    def is_low_stock(self):
        return self.quantity < self.safety_stock


class StockIn(StaffFkMixin, models.Model):
    """入库记录"""

    staff_fk_fields = (("operator", "operator_emp"),)
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, verbose_name=_("物品"))
    quantity = models.IntegerField(verbose_name=_("入库数量"))
    supplier = models.CharField(max_length=100, blank=True, verbose_name=_("供应商"))
    date = models.DateField(verbose_name=_("入库日期"))
    operator = models.CharField(max_length=30, blank=True, verbose_name=_("操作人"))
    operator_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_ins", verbose_name=_("操作人档案"),
    )

    class Meta:
        verbose_name = _("入库记录")
        verbose_name_plural = verbose_name
        ordering = ["-date"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            self.item.quantity += self.quantity
            self.item.save()
        super().save(*args, **kwargs)


class StockOut(StaffFkMixin, models.Model):
    """领用记录"""

    staff_fk_fields = (("taken_by", "taken_by_emp"),)
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, verbose_name=_("物品"))
    quantity = models.IntegerField(verbose_name=_("领用数量"))
    taken_by = models.CharField(max_length=30, blank=True, verbose_name=_("领用人"))
    taken_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_outs", verbose_name=_("领用人档案"),
    )
    date = models.DateField(verbose_name=_("领用日期"))

    class Meta:
        verbose_name = _("领用记录")
        verbose_name_plural = verbose_name
        ordering = ["-date"]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            self.item.quantity -= self.quantity
            self.item.save()
        super().save(*args, **kwargs)


class MaintenanceOrder(StaffFkMixin, models.Model):
    """设备报修工单"""

    staff_fk_fields = (("reported_by", "reported_by_emp"),)
    STATUS_CHOICES = [
        ("pending", _("待处理")),
        ("in_progress", _("维修中")),
        ("done", _("已完成")),
    ]
    equipment_name = models.CharField(max_length=100, verbose_name=_("设备名称"))
    location = models.CharField(max_length=100, verbose_name=_("所在位置"))
    fault_description = models.TextField(verbose_name=_("故障描述"))
    reported_by = models.CharField(max_length=30, blank=True, verbose_name=_("报修人"))
    reported_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="maintenance_orders", verbose_name=_("报修人档案"),
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default="pending", verbose_name=_("状态")
    )
    reported_at = models.DateTimeField(auto_now_add=True, verbose_name=_("上报时间"))
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name=_("解决时间"))

    class Meta:
        verbose_name = _("报修工单")
        verbose_name_plural = verbose_name
        ordering = ["-reported_at"]

    def __str__(self):
        return f"{self.equipment_name} — {self.get_status_display()}"


class Inspection(StaffFkMixin, models.Model):
    """卫生巡检"""

    staff_fk_fields = (("inspector_name", "inspector_emp"),)

    inspector_name = models.CharField(max_length=30, verbose_name=_("巡检人"))
    inspector_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inspections", verbose_name=_("巡检人档案"),
    )
    area = models.CharField(max_length=100, verbose_name=_("巡检区域"))
    date = models.DateField(verbose_name=_("巡检日期"))
    result = models.CharField(
        max_length=4, choices=[("合格", _("合格")), ("不合格", _("不合格"))],
        verbose_name=_("巡检结果")
    )
    note = models.TextField(blank=True, verbose_name=_("备注"))

    class Meta:
        verbose_name = _("卫生巡检")
        verbose_name_plural = verbose_name
        ordering = ["-date"]

    def __str__(self):
        return f"{self.area} — {self.date} — {self.result}"


class Approval(StaffFkMixin, models.Model):
    """审批流程（Approval）"""

    staff_fk_fields = (("applicant_name", "applicant_emp"),)

    applicant_name = models.CharField(max_length=30, verbose_name=_("申请人"))
    applicant_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approvals", verbose_name=_("申请人档案"),
    )
    approval_type = models.CharField(
        max_length=10,
        choices=[("leave", _("请假")), ("purchase", _("采购")), ("reimburse", _("报销")), ("other", _("其他"))],
        verbose_name=_("审批类型")
    )
    title = models.CharField(max_length=200, verbose_name=_("标题"))
    content = models.TextField(verbose_name=_("申请内容"))
    status = models.CharField(
        max_length=10,
        choices=[("pending", _("待审批")), ("approved", _("已通过")), ("rejected", _("已驳回"))],
        default="pending", verbose_name=_("状态")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("申请时间"))

    class Meta:
        verbose_name = _("审批流程")
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.get_status_display()}"
