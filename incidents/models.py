from django.db import models
from django.utils.translation import gettext_lazy as _

from nursing_erp.staff_fk import StaffFkMixin


class IncidentReport(StaffFkMixin, models.Model):
    """异常情况一键上报"""

    staff_fk_fields = (("handled_by", "handled_by_emp"),)

    class Category(models.TextChoices):
        FALL = "fall", _("摔倒")
        ILLNESS = "illness", _("突发不适")
        MOOD = "mood", _("情绪异常")
        REFUSE_EAT = "refuse_eat", _("拒食")
        WANDER = "wander", _("走失风险")
        SKIN = "skin", _("皮肤破损")
        OTHER = "other", _("其他")

    class Severity(models.TextChoices):
        INFO = "info", _("一般")
        WARNING = "warning", _("紧急")
        DANGER = "danger", _("危急")

    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="incidents",
        verbose_name=_("老人")
    )
    category = models.CharField(max_length=15, choices=Category.choices, verbose_name=_("异常类型"))
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.INFO, verbose_name=_("严重程度")
    )
    description = models.TextField(blank=True, verbose_name=_("补充说明"))
    handled = models.BooleanField(default=False, verbose_name=_("已处理"))
    handled_by = models.CharField(max_length=30, blank=True, verbose_name=_("处理人"))
    handled_by_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="handled_incidents", verbose_name=_("处理人档案"),
    )
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name=_("处理时间"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("上报时间"))

    class Meta:
        verbose_name = _("异常记录")
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["handled", "severity"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.resident.name} — {self.get_category_display()} — {self.created_at.strftime('%m-%d %H:%M')}"
