from django.db import models


class IncidentReport(models.Model):
    """异常情况一键上报"""

    class Category(models.TextChoices):
        FALL = "fall", "摔倒"
        ILLNESS = "illness", "突发不适"
        MOOD = "mood", "情绪异常"
        REFUSE_EAT = "refuse_eat", "拒食"
        WANDER = "wander", "走失风险"
        SKIN = "skin", "皮肤破损"
        OTHER = "other", "其他"

    class Severity(models.TextChoices):
        INFO = "info", "一般"
        WARNING = "warning", "紧急"
        DANGER = "danger", "危急"

    resident = models.ForeignKey(
        "residents.Resident", on_delete=models.CASCADE, related_name="incidents",
        verbose_name="老人"
    )
    category = models.CharField(max_length=15, choices=Category.choices, verbose_name="异常类型")
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.INFO, verbose_name="严重程度"
    )
    description = models.TextField(blank=True, verbose_name="补充说明")
    handled = models.BooleanField(default=False, verbose_name="已处理")
    handled_by = models.CharField(max_length=30, blank=True, verbose_name="处理人")
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="上报时间")

    class Meta:
        verbose_name = "异常上报"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["handled", "severity"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.resident.name} — {self.get_category_display()} — {self.created_at.strftime('%m-%d %H:%M')}"
