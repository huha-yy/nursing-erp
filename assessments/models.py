"""入住评估→定级 — 路线图阶段二收尾（2026-08-24）：贴国标 GB/T 42195-2022。

核心口径：
- 4 个一级指标 26 个二级指标（目录 AssessmentItem，国标原文项目名，后台可调）；
  各项 0-10 或 0-5 分，原始满分 190（自理 8×10 + 运动 4×10 + 精神 9×5 + 感知觉 5×5）
- 总分归一化到 0-100（越高越受损）：round(原始分和 × 100 / 目录满分和)——
  对"在用目录"实时求满分，后台调目录不破坏 0-100 语义
- 等级分段是国标常量（硬编码）：0-20→0级 能力完好 / 21-45→1级 / 46-65→2级 /
  66-90→3级 / 91-100→4级 完全丧失
- 等级→护理档是院内政策（配置表 GradeLevelMap，仿 FeeRule 缺行 fail-loud）；
  种子不含「失智」——失智无法由分数推出，只能定级时人工改判（reason 必填）
- 定级确认闭环：confirm() 原子地更新 Resident.care_level 并自动生成关联
  CareLevelChange（from==to 也留痕：评估单本身就是等级的监管依据，不是差量信号）
- 分数快照语义：AssessmentScore 行上只存得分，上限读目录（PROTECT 防删被引用项；
  目录改名/调上限不腐蚀历史单——总分落在单上，recalculate 后不再随目录漂移）
"""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from nursing_erp.staff_fk import StaffFkMixin
from residents.models import Resident


class GradeMapMissing(LookupError):  # noqa: N818 — 仿 FeeRuleMissing 命名
    """等级映射表缺行 — fail-loud：管理员须先在后台「等级映射表」补配置再定级。"""


class AssessmentItem(models.Model):
    """评估项目目录 — 国标 26 项二级指标骨架（后台可调；分值落在
    AssessmentScore 行上，目录后续改名/调上限不腐蚀历史单的已算总分）。"""

    class Dimension(models.TextChoices):
        ADL = "自理能力", "自理能力"
        MOTOR = "基础运动能力", "基础运动能力"
        MENTAL = "精神状态", "精神状态"
        PERCEPTION = "感知觉与社会参与", "感知觉与社会参与"

    dimension = models.CharField(max_length=10, choices=Dimension.choices, verbose_name="一级指标")
    name = models.CharField(max_length=30, verbose_name="二级指标")
    max_score = models.PositiveSmallIntegerField(default=10, verbose_name="分值上限")
    order = models.PositiveSmallIntegerField(verbose_name="展示顺序")
    is_active = models.BooleanField(default=True, verbose_name="在用")

    class Meta:
        verbose_name = "评估项目"
        verbose_name_plural = "评估项目目录"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["dimension", "name"], name="item_dim_name_unique"),
        ]

    def __str__(self):
        return f"{self.get_dimension_display()}·{self.name}"


class GradeLevelMap(models.Model):
    """能力等级→护理档映射 — 院内政策，后台可改（仿 FeeRule）。
    种子不含「失智」：失智无法由分数推出，只能定级时人工改判并填原因。"""

    GRADE_CHOICES = [(i, f"{i}级") for i in range(5)]

    grade = models.PositiveSmallIntegerField(
        choices=GRADE_CHOICES, unique=True, verbose_name="能力等级"
    )
    care_level = models.CharField(
        max_length=10, choices=Resident.CareLevel.choices, verbose_name="护理档"
    )

    class Meta:
        verbose_name = "等级映射"
        verbose_name_plural = "等级映射表"
        ordering = ["grade"]

    def __str__(self):
        return f"{self.get_grade_display()} → {self.care_level}"

    @classmethod
    def get_level_for_grade(cls, grade: int) -> str:
        row = cls.objects.filter(grade=grade).first()
        if row is None:
            raise GradeMapMissing(
                f"等级映射表缺行：{grade}级 —— 请先在后台「等级映射表」补配置再定级"
            )
        return row.care_level


class Assessment(StaffFkMixin, models.Model):
    """入住评估单 — 26 项打分 → 总分/等级/建议护理档 → 定级确认。

    评估员1=医护责任人（StaffFkMixin 挂员工档案）；评估员2 仅记名——
    国标要求双人评估（至少 1 名医护背景），双签只记录不做工作流。
    注意：queryset.update() 绕过 StaffFkMixin；total/grade/suggested 只能
    经 recalculate() 写（服务层同一事务写完明细行后调用）。
    """

    staff_fk_fields = (("assessor1", "assessor1_emp"),)

    class Status(models.TextChoices):
        DRAFT = "draft", "待定级"
        CONFIRMED = "confirmed", "已定级"

    GRADE_LABELS = {
        0: "0级 能力完好", 1: "1级 轻度受损", 2: "2级 中度受损",
        3: "3级 重度受损", 4: "4级 完全丧失",
    }
    # GB/T 42195-2022 分段常量（国标口径，非院内配置）：总分越高越受损
    BANDS = ((0, 20, 0), (21, 45, 1), (46, 65, 2), (66, 90, 3), (91, 100, 4))

    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="assessments", verbose_name="老人"
    )
    assess_date = models.DateField(verbose_name="评估日期")
    assessor1 = models.CharField(max_length=30, verbose_name="评估员1（医护）")
    assessor1_emp = models.ForeignKey(
        "staff.Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assessments_primary", verbose_name="评估员1档案",
    )
    assessor2 = models.CharField(max_length=30, verbose_name="评估员2")
    total_score = models.PositiveSmallIntegerField(default=0, verbose_name="总分(0-100)")
    grade = models.PositiveSmallIntegerField(
        default=0, choices=GradeLevelMap.GRADE_CHOICES, verbose_name="能力等级"
    )
    suggested_level = models.CharField(
        max_length=10, blank=True, default="", choices=Resident.CareLevel.choices,
        verbose_name="建议护理档",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, verbose_name="状态"
    )
    final_level = models.CharField(
        max_length=10, blank=True, default="", choices=Resident.CareLevel.choices,
        verbose_name="定级结果",
    )
    confirm_reason = models.CharField(max_length=200, blank=True, verbose_name="定级说明")
    confirmed_by = models.CharField(max_length=30, blank=True, verbose_name="定级人")
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="定级时间")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "入住评估"
        verbose_name_plural = verbose_name
        ordering = ["-assess_date", "-id"]
        indexes = [models.Index(fields=["resident", "status"])]

    def __str__(self):
        return f"{self.resident.name} {self.assess_date} {self.total_score}分"

    @classmethod
    def grade_for_score(cls, total: int) -> int:
        """0-100 → 0-4 能力等级（越高越受损，国标分段常量）。"""
        for lo, hi, grade in cls.BANDS:
            if lo <= total <= hi:
                return grade
        raise ValueError(f"总分越界：{total}（应在 0-100）")

    def recalculate(self) -> None:
        """从明细行重算 total/grade/suggested —— 唯一写这三列的入口；
        服务层同一事务写完 26 行后调用，之后不随目录改动漂移。"""
        rows = list(self.scores.select_related("item"))
        max_sum = sum(r.item.max_score for r in rows)
        score_sum = sum(r.score for r in rows)
        self.total_score = round(score_sum * 100 / max_sum) if max_sum else 0
        self.grade = self.grade_for_score(self.total_score)
        self.suggested_level = GradeLevelMap.get_level_for_grade(self.grade)
        self.save(update_fields=["total_score", "grade", "suggested_level", "updated_at"])

    def confirm(self, operator: str = "", final_level: str = "", reason: str = "") -> None:
        """定级确认（原子）：落定级 → 更新 Resident.care_level → 自动生成
        关联 CareLevelChange（from==to 也留痕：评估单是等级的监管依据）。

        - final_level 缺省=建议档；改判（≠建议）时 reason 必填；
          失智只能经此改判进入（映射表刻意无此行）
        - 幂等拒绝（raise 而非静默返回）：第二次确认可能带不同 final_level，
          静默吞掉会让调用方误以为按其参数生效
        - change_date = assess_date：定级针对评估当日能力，补录剧本与月度出账对齐
        """
        from residents.models import CareLevelChange  # 惰性引用，避免加载环

        with transaction.atomic():
            # 锁序恒定 resident → assessment，防死锁；SQLite 退化为事务级锁
            resident = Resident.objects.select_for_update().get(pk=self.resident_id)
            locked = Assessment.objects.select_for_update().get(pk=self.pk)
            if locked.status == self.Status.CONFIRMED:
                raise ValueError("该评估已定级，不可重复确认")
            if not locked.suggested_level:
                raise ValueError("评估分值缺失或映射缺行，无法定级")

            target = final_level or locked.suggested_level
            if target not in Resident.CareLevel.values:
                raise ValueError(f"未知护理档：{target}")
            if target != locked.suggested_level and not reason.strip():
                raise ValueError("定级结果与评估建议不一致，必须填写原因")

            old_level = resident.care_level
            self.status = self.Status.CONFIRMED
            self.final_level = target
            self.confirm_reason = reason
            self.confirmed_by = operator
            self.confirmed_at = timezone.now()
            self.save(update_fields=[
                "status", "final_level", "confirm_reason", "confirmed_by", "confirmed_at",
                "updated_at",
            ])

            resident.care_level = target
            resident.save(update_fields=["care_level"])  # 走 save()：床位串缓存顺带对齐

            summary = (
                f"入住评估定级：总分 {self.total_score}（{self.GRADE_LABELS[self.grade]}）"
                f"·建议 {self.suggested_level}·评估员 {self.assessor1}/{self.assessor2}"
            )
            if reason.strip():
                summary += f"·{reason.strip()}"
            CareLevelChange.objects.create(
                resident=resident, from_level=old_level, to_level=target,
                change_date=self.assess_date, reason=summary,
                changed_by=operator, assessment=self,
            )


class AssessmentScore(models.Model):
    """评估明细 — 一单 26 行；行上只存得分，上限读目录（快照语义）。"""

    assessment = models.ForeignKey(
        Assessment, on_delete=models.CASCADE, related_name="scores", verbose_name="评估单"
    )
    item = models.ForeignKey(
        AssessmentItem, on_delete=models.PROTECT, related_name="score_rows", verbose_name="项目"
    )
    score = models.PositiveSmallIntegerField(verbose_name="得分")

    class Meta:
        verbose_name = "评估明细"
        verbose_name_plural = verbose_name
        ordering = ["item__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "item"], name="score_assessment_item_unique"
            ),
        ]

    def __str__(self):
        return f"{self.assessment_id}#{self.item_id}:{self.score}"

    def clean(self):
        if self.score > self.item.max_score:
            raise ValidationError(
                f"{self.item.name} 得分 {self.score} 超上限 {self.item.max_score}"
            )
