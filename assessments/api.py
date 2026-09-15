"""入住评估 API — /assessments/ 看板与后续 AI 侧只读查询的后端。

楼栋守卫：列表/详情走 scope_filter / scope_get_or_404；建单/定级走
resident_for_write / _assessment_for_write（404 缺失 / 403 跨楼），
均照抄 billing/api.py 的守卫范式。
"""

from datetime import date as date_type

from django.utils.translation import gettext as _n
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from auditlog.record import record
from nursing_erp.api_scope import (
    resident_for_write,
    resolve_building_scope,
    scope_filter,
    scope_get_or_404,
)

from .models import Assessment
from .services import create_assessment, review_lists

router = Router(tags=["入住评估"])


class AssessmentIn(Schema):
    """建单入参 — scores={item_id: score}，服务层校验全覆盖与上限。"""
    resident_id: int
    assess_date: date_type | None = None
    assessor1: str
    assessor2: str
    scores: dict[int, int]


class ConfirmIn(Schema):
    """定级入参 — final_level 缺省=建议档；改判必须带 reason。"""
    final_level: str = ""
    reason: str = ""
    confirmed_by: str = ""


def _assessment_out(a: Assessment, detail: bool = False) -> dict:
    out = {
        "id": a.id,
        "resident_id": a.resident_id,
        "resident_name": a.resident.name,
        "building": a.resident.building,
        "room": a.resident.room,
        "assess_date": a.assess_date.isoformat(),
        "assessor1": a.assessor1,
        "assessor2": a.assessor2,
        "total_score": a.total_score,
        "grade": a.grade,
        "grade_display": Assessment.GRADE_LABELS[a.grade],
        "suggested_level": a.suggested_level,
        "status": a.status,
        "status_display": a.get_status_display(),
        "final_level": a.final_level,
        "confirmed_by": a.confirmed_by,
        "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None,
    }
    if detail:
        out["scores"] = [
            {
                "item_id": s.item_id,
                "dimension": s.item.dimension,
                "name": s.item.name,
                "score": s.score,
                "max_score": s.item.max_score,
            }
            for s in a.scores.select_related("item")
        ]
    return out


def _operator_name(request, override: str = "") -> str:
    if override:
        return override
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            return user.employee.name
        except Exception:
            return user.username
    return "api"


def _assessment_for_write(request, assessment_id: int) -> Assessment:
    """定级守卫（照抄 billing _bill_for_write）：缺失 404 / 跨楼 403。"""
    a = Assessment.objects.select_related("resident").filter(pk=assessment_id).first()
    if a is None:
        raise HttpError(404, _n("评估单不存在"))
    scope = resolve_building_scope(request)
    if scope and a.resident.building != scope:
        raise HttpError(
            403,
            _n("无权操作 {} 的评估单（当前范围：{}）").format(a.resident.building, scope),
        )
    return a


@router.get("/assessments/", response=list[dict])
@paginate(PageNumberPagination, page_size=50)
def list_assessments(request, resident_id: int = 0, status: str = ""):
    qs = Assessment.objects.select_related("resident").all()
    if resident_id:
        qs = qs.filter(resident_id=resident_id)
    if status:
        qs = qs.filter(status=status)
    qs = scope_filter(qs, request, "resident__building")
    return [_assessment_out(a) for a in qs]


@router.get("/assessments/review/", response=dict)
def assessment_review(request):
    """评估状态盘点（国标 12 个月复评）——AI 侧"谁该复评/谁还没评"的数据源。

    rows 只含可行动两态（待评估/待复评，state 标签区分）；期内已评只给
    计数 ok_count——36 人量级下不稀释注入上限。楼栋 scope 生效（楼长只看本楼）。
    注意：本路由须注册在 /assessments/{id}/ 之前（同名段会被 int 参数吞 422）。
    """
    scope = resolve_building_scope(request)
    rv = review_lists(building=scope or "")

    def _row(state: str, r: dict) -> dict:
        res = r["resident"]
        return {
            "state": state,
            "resident_id": res.id,
            "resident_name": res.name,
            "building": res.building,
            "room": res.room,
            "care_level": res.care_level,
            "last_assessed": r["last_assessed"].isoformat() if r["last_assessed"] else None,
        }

    return {
        "rows": (
            [_row("待评估", r) for r in rv["pending_first"]]
            + [_row("待复评", r) for r in rv["due_review"]]
        ),
        "pending_first_count": len(rv["pending_first"]),
        "due_review_count": len(rv["due_review"]),
        "ok_count": len(rv["ok"]),
    }


@router.get("/assessments/{assessment_id}/", response=dict)
def get_assessment(request, assessment_id: int):
    a = scope_get_or_404(Assessment, assessment_id, request, field="resident__building")
    return _assessment_out(a, detail=True)


@router.post("/assessments/", response=dict)
def create_assessment_api(request, payload: AssessmentIn):
    """建评估单（draft）——建单即见总分/等级/建议档（detail 输出）。"""
    resident = resident_for_write(request, payload.resident_id)
    assess_date = payload.assess_date or date_type.today()
    try:
        a = create_assessment(
            resident, assess_date, payload.assessor1, payload.assessor2, payload.scores
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return _assessment_out(a, detail=True)


@router.post("/assessments/{assessment_id}/confirm/", response=dict)
def confirm_assessment(request, assessment_id: int, payload: ConfirmIn | None = None):
    """定级确认——更新老人护理档并自动生成关联变更记录（见模型 confirm docstring）。"""
    a = _assessment_for_write(request, assessment_id)
    payload = payload or ConfirmIn()
    try:
        a.confirm(
            operator=_operator_name(request, payload.confirmed_by),
            final_level=payload.final_level, reason=payload.reason,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    record(request, action="评估定级确认",
           target=f"{a.resident.name}（{a.resident.building}{a.resident.room}）→ "
                  f"{payload.final_level or a.suggested_level}",
           detail=f"总分 {a.total_score} · {payload.reason or '无备注'}",
           target_model="assessments.Assessment", target_id=a.id)
    return _assessment_out(a)
