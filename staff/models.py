from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from nursing_erp.staff_fk import StaffFkMixin


class Employee(models.Model):
    """员工档案"""

    class Dept(models.TextChoices):
        DIRECTOR = "院长", _("院长")
        NURSING = "护理科", _("护理科")
        LOGISTICS = "总务科", _("总务科")
        ADMIN = "综合办", _("综合办")
        MEDICAL = "医务科", _("医务科")
        FINANCE = "财务科", _("财务科")
        SECURITY = "安全保卫科", _("安全保卫科")

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("登录账号"))
    name = models.CharField(max_length=30, verbose_name=_("姓名"))
    dept = models.CharField(max_length=20, choices=Dept.choices, verbose_name=_("部门"))
    building = models.CharField(max_length=20, blank=True, verbose_name=_("负责楼栋"))
    phone = models.CharField(max_length=15, blank=True, verbose_name=_("手机号"))
    is_caregiver = models.BooleanField(default=True, verbose_name=_("是否护理员"))
    hire_date = models.DateField(null=True, blank=True, verbose_name=_("入职日期"))

    class Meta:
        verbose_name = _("员工档案")
        verbose_name_plural = verbose_name
        ordering = ["dept", "name"]

    def __str__(self):
        return self.name


class Schedule(models.Model):
    """排班表 — 做六休一，12h 班制"""

    class Shift(models.TextChoices):
        DAY = "白班", _("白班(7-19)")
        NIGHT = "夜班", _("夜班(19-7)")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="schedules", verbose_name=_("员工")
    )
    date = models.DateField(verbose_name=_("日期"))
    shift = models.CharField(max_length=4, choices=Shift.choices, verbose_name=_("班次"))
    building = models.CharField(max_length=20, blank=True, verbose_name=_("楼栋"))
    floor = models.CharField(max_length=10, blank=True, verbose_name=_("楼层"))
    task_note = models.CharField(max_length=200, blank=True, verbose_name=_("任务备注"))

    class Meta:
        verbose_name = _("排班表")
        verbose_name_plural = verbose_name
        unique_together = [("employee", "date", "shift")]
        ordering = ["date", "shift"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["building", "date"]),
        ]

    def __str__(self):
        return f"{self.employee.name} — {self.date} {self.get_shift_display()}"


class Attendance(models.Model):
    """考勤打卡"""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="attendances", verbose_name=_("员工")
    )
    date = models.DateField(verbose_name=_("日期"))
    clock_in = models.DateTimeField(verbose_name=_("上班打卡"))
    clock_out = models.DateTimeField(null=True, blank=True, verbose_name=_("下班打卡"))

    class Meta:
        verbose_name = _("考勤记录")
        verbose_name_plural = verbose_name
        unique_together = [("employee", "date")]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.employee.name} — {self.date}"


class Task(StaffFkMixin, models.Model):
    """任务派发"""

    staff_fk_fields = (("assigner_name", "assigner_emp"),)

    assigner_name = models.CharField(max_length=30, verbose_name=_("派发人"))
    assigner_emp = models.ForeignKey(
        "Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_tasks", verbose_name=_("派发人档案"),
    )
    assignee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="tasks", verbose_name=_("接收人")
    )
    title = models.CharField(max_length=200, verbose_name=_("任务标题"))
    content = models.TextField(blank=True, verbose_name=_("任务内容"))
    deadline = models.DateField(null=True, blank=True, verbose_name=_("截止日期"))
    is_completed = models.BooleanField(default=False, verbose_name=_("已完成"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("创建时间"))

    class Meta:
        verbose_name = _("任务派发")
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {'✅' if self.is_completed else '⏳'}"


class Performance(models.Model):
    """绩效考核"""
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="performances", verbose_name=_("员工")
    )
    month = models.CharField(max_length=7, verbose_name=_("考核月份"))
    attendance_score = models.IntegerField(default=100, verbose_name=_("出勤分"))
    quality_score = models.IntegerField(default=100, verbose_name=_("工作质量分"))
    total_score = models.IntegerField(default=100, verbose_name=_("总分"))
    comment = models.TextField(blank=True, verbose_name=_("评语"))

    class Meta:
        verbose_name = _("绩效考核")
        verbose_name_plural = verbose_name
        unique_together = [("employee", "month")]
        ordering = ["-month", "employee__name"]

    def __str__(self):
        return f"{self.employee.name} — {self.month} — {self.total_score}分"
