"""入住评估服务层 — 建单校验/原子写入 与 复评盘点。"""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils.translation import gettext as _n

from residents.models import Resident

from .models import Assessment, AssessmentItem, AssessmentScore

# 国标：每 12 个月复评一次
REVIEW_INTERVAL = timedelta(days=365)


def create_assessment(resident, assess_date, assessor1: str, assessor2: str,
                      scores: dict[int, int]) -> Assessment:
    """建评估单（draft）。scores={item_id: score}，须恰好覆盖全部在用目录项且
    0≤score≤该项上限；缺项/越界/未知项 raise ValueError（fail-loud）。
    评估单 + 明细 + recalculate 同一事务，失败零残留。
    """
    catalog = list(AssessmentItem.objects.filter(is_active=True))
    if not catalog:
        raise ValueError(_n("评估项目目录为空——请先在后台「评估项目目录」配置"))
    if not (assessor1 or "").strip() or not (assessor2 or "").strip():
        raise ValueError(_n("评估员1、评估员2 均不能为空（国标要求双人评估）"))

    by_id = {item.id: item for item in catalog}
    given = set(scores)
    expected = set(by_id)
    missing, extra = expected - given, given - expected
    if missing or extra:
        parts = []
        if missing:
            parts.append(_n("缺 {} 项").format(len(missing)))
        if extra:
            parts.append(_n("多 {} 项（非在用目录项）").format(len(extra)))
        raise ValueError(
            _n("评估明细须覆盖全部 {} 项，{}").format(len(catalog), "、".join(parts))
        )

    for item in catalog:
        score = scores[item.id]
        if not isinstance(score, int) or isinstance(score, bool):
            raise ValueError(_n("{} 得分须为整数，收到：{!r}").format(item.name, score))
        if not 0 <= score <= item.max_score:
            raise ValueError(_n("{} 得分 {} 超出 0-{}").format(item.name, score, item.max_score))

    with transaction.atomic():
        assessment = Assessment.objects.create(
            resident=resident, assess_date=assess_date,
            assessor1=assessor1, assessor2=assessor2,
        )
        AssessmentScore.objects.bulk_create(
            [AssessmentScore(assessment=assessment, item=item, score=scores[item.id])
             for item in catalog]
        )
        assessment.recalculate()
    return assessment


def review_lists(building: str = "") -> dict[str, list[dict]]:
    """在住（bed 非空，对齐 billing 在住口径）评估状态盘点：
    pending_first（无已确认单→待评估）/ due_review（最近已确认 > 12 个月→待复评）/
    ok（期内已评，含最近评估日期）。36 人量级 Python 侧分类足够。
    building 非空时只盘该楼（API 楼长 scope 用；页面全院）。
    """
    last = Assessment.objects.filter(
        resident=OuterRef("pk"), status=Assessment.Status.CONFIRMED,
    ).order_by("-assess_date").values("assess_date")[:1]
    cutoff = date.today() - REVIEW_INTERVAL
    pending, due, ok = [], [], []
    residents = Resident.objects.filter(bed__isnull=False)
    if building:
        residents = residents.filter(building=building)
    residents = (
        residents.annotate(last_assessed=Subquery(last))
        .order_by("building", "name")
    )
    for r in residents:
        row = {"resident": r, "last_assessed": r.last_assessed}
        if r.last_assessed is None:
            pending.append(row)
        elif r.last_assessed <= cutoff:
            due.append(row)
        else:
            ok.append(row)
    return {"pending_first": pending, "due_review": due, "ok": ok}
