from django.db import models

from nursing_erp.staff_fk import StaffFkMixin


class InventoryItem(models.Model):
    """库存物品"""

    class Category(models.TextChoices):
        CONSUMABLE = "护理耗材", "护理耗材"
        MEDICAL = "医疗器械", "医疗器械"
        PROTECTIVE = "防护用品", "防护用品"
        CLEANING = "清洁消毒", "清洁消毒"
        ASSISTIVE = "辅助器具", "辅助器具"

    name = models.CharField(max_length=100, verbose_name="物品名称")
    category = models.CharField(max_length=10, choices=Category.choices, verbose_name="分类")
    quantity = models.IntegerField(default=0, verbose_name="库存数量")
    unit = models.CharField(max_length=10, verbose_name="单位")
    safety_stock = models.IntegerField(default=10, verbose_name="安全库存")

    class Meta:
        verbose_name = "库存物品"
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
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, verbose_name="物品")
    quantity = models.IntegerField(verbose_name="入库数量")
    supplier = models.CharField(max_length=100, blank=True, verbose_name="供应商")
    date = models.DateField(verbose_name="入库日期")
    operator = models.CharField(max_length=30, blank=True, verbose_name="操作人")
    operator_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_ins", verbose_name="操作人档案",
    )

    class Meta:
        verbose_name = "入库记录"
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
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, verbose_name="物品")
    quantity = models.IntegerField(verbose_name="领用数量")
    taken_by = models.CharField(max_length=30, blank=True, verbose_name="领用人")
    taken_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_outs", verbose_name="领用人档案",
    )
    date = models.DateField(verbose_name="领用日期")

    class Meta:
        verbose_name = "领用记录"
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
        ("pending", "待处理"),
        ("in_progress", "维修中"),
        ("done", "已完成"),
    ]
    equipment_name = models.CharField(max_length=100, verbose_name="设备名称")
    location = models.CharField(max_length=100, verbose_name="所在位置")
    fault_description = models.TextField(verbose_name="故障描述")
    reported_by = models.CharField(max_length=30, blank=True, verbose_name="报修人")
    reported_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="maintenance_orders", verbose_name="报修人档案",
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default="pending", verbose_name="状态"
    )
    reported_at = models.DateTimeField(auto_now_add=True, verbose_name="上报时间")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="解决时间")

    class Meta:
        verbose_name = "报修工单"
        verbose_name_plural = verbose_name
        ordering = ["-reported_at"]

    def __str__(self):
        return f"{self.equipment_name} — {self.get_status_display()}"


class Inspection(StaffFkMixin, models.Model):
    """卫生巡检"""

    staff_fk_fields = (("inspector_name", "inspector_emp"),)

    inspector_name = models.CharField(max_length=30, verbose_name="巡检人")
    inspector_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="inspections", verbose_name="巡检人档案",
    )
    area = models.CharField(max_length=100, verbose_name="巡检区域")
    date = models.DateField(verbose_name="巡检日期")
    result = models.CharField(
        max_length=4, choices=[("合格", "合格"), ("不合格", "不合格")],
        verbose_name="巡检结果"
    )
    note = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "卫生巡检"
        verbose_name_plural = verbose_name
        ordering = ["-date"]

    def __str__(self):
        return f"{self.area} — {self.date} — {self.result}"


class Approval(StaffFkMixin, models.Model):
    """审批单"""

    staff_fk_fields = (("applicant_name", "applicant_emp"),)

    applicant_name = models.CharField(max_length=30, verbose_name="申请人")
    applicant_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approvals", verbose_name="申请人档案",
    )
    approval_type = models.CharField(
        max_length=10,
        choices=[("leave","请假"),("purchase","采购"),("reimburse","报销"),("other","其他")],
        verbose_name="审批类型"
    )
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(verbose_name="申请内容")
    status = models.CharField(
        max_length=10,
        choices=[("pending","待审批"),("approved","已通过"),("rejected","已驳回")],
        default="pending", verbose_name="状态"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="申请时间")

    class Meta:
        verbose_name = "审批单"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.get_status_display()}"
