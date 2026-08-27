from django.contrib.auth.models import User
from django.db import models


class OperationLog(models.Model):
    """操作日志——「谁、何时、对什么对象、做了什么」统一留痕。

    采集两层（2026-08-25 设计）：
    1. 显式埋点 record()：点餐/退餐/评估确认等关键业务动作，人话摘要；
    2. 中间件兜底 AuditMiddleware：所有 /api/* 写请求自动留痕，埋点漏了
       也不丢事件（同一请求埋点已记则跳过——一事一行）。
    口径红线：不落请求体——密码/身份证等敏感字段从源头就不进日志；
    /admin/* 台账操作由 Django 自带 LogEntry 覆盖，不重复记。
    """

    class Actor(models.TextChoices):
        STAFF = "staff", "员工"
        FAMILY = "family", "家属"
        AI = "ai", "AI 助手"
        SYSTEM = "system", "系统"

    actor_type = models.CharField("身份", max_length=10, choices=Actor.choices)
    actor_name = models.CharField("操作人", max_length=40)
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="operation_logs", verbose_name="账号",
    )
    action = models.CharField("动作", max_length=30)
    target = models.CharField("对象", max_length=120, blank=True)
    target_model = models.CharField("对象模型", max_length=50, blank=True)
    target_id = models.CharField("对象ID", max_length=20, blank=True)
    detail = models.TextField("说明", blank=True)
    method = models.CharField("方法", max_length=8, blank=True)
    path = models.CharField("路径", max_length=200, blank=True)
    status_code = models.PositiveIntegerField("状态码", null=True, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "业务操作日志"
        verbose_name_plural = "业务操作日志"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor_type", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.actor_name} {self.action} {self.target} {self.created_at:%m-%d %H:%M}"
