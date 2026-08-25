"""家属端 API — 家属页 JS（session）与 dl-control（X-API-Key + X-Family-Token）共用。

数据边界（红线）：只出绑定老人的数据；id_card / Resident.notes / 异常上报
永不出现；诊断与过敏史对家属开放（2026-08-24 产品决策）。
返回裸数组/对象——家属绑定 1-3 人，无分页信封（页面 JS 与 dl-control 都不剥 items）。
"""

import re
from datetime import date, timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Count, Min, Sum
from ninja import NinjaAPI, Router, Schema
from ninja.errors import HttpError

from assessments.models import Assessment
from auditlog.record import record
from billing.models import MonthlyBill
from billing.services import current_month
from meals.api import _assert_no_active_duplicate, _format_order
from meals.models import MealOrder, WeekMenu
from residents.models import HealthRecord, MedicationRecord, NursingLog, Resident

from .auth import api_key_auth, family_auth
from .models import FamilyMember

router = Router(tags=["家属端"])

# version 同时决定 URL namespace——与员工 api 的 "api-1.0.0" 区分开（urls.W005）
family_api = NinjaAPI(title="家属端 API", version="family-1.0.0", auth=family_auth)
family_api.add_router("/", router)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# ---- Schemas ----

class LoginIn(Schema):
    """家属登录入参（dl-control /auth/family-login 的后端）。"""

    phone: str
    password: str


class FamilyMealOrderIn(Schema):
    """家属代点入参 — 无 ordered_by 字段：归属必须服务端生成，防冒名。"""

    resident_id: int
    date: str  # "2026-08-24"
    meal_type: str  # 早餐/午餐/晚餐
    dish_ids: list[int]
    special_requests: str = ""


class CancelIn(Schema):
    reason: str = ""


# ---- 绑定守卫与工具（口径沿 nursing_erp/api_scope.py：读 404 不泄露存在性、写 403）----

def _bound_ids(fm: FamilyMember) -> set[int]:
    return set(fm.bindings.values_list("resident_id", flat=True))


def _resident_for_read(fm: FamilyMember, resident_id: int) -> Resident:
    r = Resident.objects.filter(pk=resident_id).first()
    if r is None or resident_id not in _bound_ids(fm):
        raise HttpError(404, "老人不存在或未与您绑定")
    return r


def _resident_for_write(fm: FamilyMember, resident_id: int) -> Resident:
    r = Resident.objects.filter(pk=resident_id).first()
    if r is None:
        raise HttpError(404, "老人不存在")
    if resident_id not in _bound_ids(fm):
        raise HttpError(403, "该老人未与您绑定，无法代操作")
    return r


def _order_for_write(fm: FamilyMember, order_id: int) -> MealOrder:
    order = MealOrder.objects.select_related("resident").filter(pk=order_id).first()
    if order is None:
        raise HttpError(404, "订单不存在")
    if order.resident_id not in _bound_ids(fm):
        raise HttpError(403, "该订单不属于您绑定的老人")
    return order


def _attribution(fm: FamilyMember, resident_id: int) -> str:
    """写归属串 → MealOrder.ordered_by / 改退餐 changed_by（≤30 字上限内）。"""
    b = fm.bindings.filter(resident_id=resident_id).first()
    rel = b.get_relation_display() if b else ""
    return f"家属-{fm.name}（{rel}）"


def _assessment_summary(a: Assessment | None) -> dict | None:
    if a is None:
        return None
    return {
        "id": a.id,
        "assess_date": str(a.assess_date),
        "total_score": a.total_score,
        "grade": a.grade,
        "grade_display": Assessment.GRADE_LABELS.get(a.grade, ""),
        "suggested_level": a.suggested_level,
        "final_level": a.final_level,  # 待定级时为空串
        "status": a.status,
        "status_display": a.get_status_display(),
    }


def _arrears_of(resident: Resident, month: str) -> dict | None:
    """单老人欠费聚合（截止月含更早）——billing.arrears_stats 只按楼过滤，家属口径自算。"""
    agg = MonthlyBill.objects.filter(
        resident=resident, status=MonthlyBill.Status.PENDING, month__lte=month
    ).aggregate(unpaid_months=Count("id"), outstanding=Sum("total"), oldest_month=Min("month"))
    if not agg["unpaid_months"]:
        return None
    return {
        "unpaid_months": agg["unpaid_months"],
        "outstanding": float(agg["outstanding"]),
        "oldest_month": agg["oldest_month"],
    }


def _log_out(log: NursingLog) -> dict:
    return {
        "id": log.id,
        "log_date": str(log.log_date),
        "category": log.category,
        "category_display": log.get_category_display(),
        "detail": log.detail,
        "staff_name": log.staff_name,
    }


def _health_out(h: HealthRecord) -> dict:
    return {
        "id": h.id,
        "record_date": str(h.record_date),
        "blood_pressure": h.blood_pressure,
        "blood_sugar": float(h.blood_sugar) if h.blood_sugar else None,
        "heart_rate": h.heart_rate,
        "weight": float(h.weight) if h.weight else None,
        "temperature": float(h.temperature) if h.temperature else None,
        "note": h.note,
    }


def _medication_out(m: MedicationRecord) -> dict:
    return {
        "id": m.id,
        "medicine_name": m.medicine_name,
        "dosage": m.dosage,
        "frequency": m.frequency,
        "frequency_display": m.get_frequency_display(),
        "start_date": str(m.start_date),
        "end_date": str(m.end_date) if m.end_date else None,
        "note": m.note,
    }


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ---- 登录（dl-control 家属对话的后端）----

@router.post("/auth/", response=dict, auth=api_key_auth)
def family_login(request, payload: LoginIn):
    """手机号+密码换 token 与绑定清单 — dl-control /auth/family-login 调用。

    只验 X-API-Key（服务间），此时还没有 family token。
    """
    user = authenticate(request, username=payload.phone, password=payload.password)
    if user is None:
        raise HttpError(401, "手机号或密码错误")
    fm = FamilyMember.objects.filter(user=user, is_active=True).first()
    if fm is None:
        raise HttpError(401, "该账号不是家属账号")
    return {
        "family_id": fm.id,
        "token": fm.token,
        "name": fm.name,
        "residents": [
            {
                "id": b.resident_id,
                "name": b.resident.name,
                "building": b.resident.building,
                "room": b.resident.room,
                "relation": b.get_relation_display(),
            }
            for b in fm.bindings.select_related("resident").order_by("resident__id")
        ],
    }


# ---- 读：总览 / 照护摘要 ----

@router.get("/overview/", response=list[dict])
def family_overview(request):
    """总览（家属首页 + AI 兜底行）：基础信息+最新评估+近期动态+今日三餐+欠费。"""
    fm = request.auth
    today = date.today()
    rows = []
    for b in fm.bindings.select_related("resident").order_by("resident__id"):
        r = b.resident
        latest = r.assessments.filter(status=Assessment.Status.CONFIRMED).order_by(
            "-assess_date", "-id"
        ).first()
        latest_health = r.health_records.order_by("-record_date", "-id").first()
        rows.append({
            "id": r.id,
            "name": r.name,
            "gender": r.gender,
            "age": r.age,
            "building": r.building,
            "room": r.room,
            "care_level": r.care_level,
            "care_level_display": r.get_care_level_display(),
            "relation": b.get_relation_display(),
            "admission_date": str(r.admission_date) if r.admission_date else None,
            "diagnosis": r.diagnosis,
            "allergies": r.allergies,
            "latest_assessment": _assessment_summary(latest),
            "recent_logs": [
                _log_out(log)
                for log in r.logs.order_by("-log_date", "-id")[:3]
            ],
            "latest_health": _health_out(latest_health) if latest_health else None,
            "today_meals": [
                _format_order(o)
                for o in r.meal_orders.filter(date=today)
                .prefetch_related("dishes").order_by("meal_type")
            ],
            "arrears": _arrears_of(r, current_month()),
        })
    return rows


@router.get("/care/", response=list[dict])
def family_care(request, resident_id: int | None = None):
    """照护摘要：缺省=全部绑定老人；指定 resident_id 时未绑定 404。"""
    fm = request.auth
    since = date.today() - timedelta(days=7)
    if resident_id is not None:
        residents = [_resident_for_read(fm, resident_id)]
    else:
        residents = [
            b.resident
            for b in fm.bindings.select_related("resident").order_by("resident__id")
        ]
    return [_care_block(r, since) for r in residents]


def _care_block(r: Resident, since: date) -> dict:
    latest_asmt = r.assessments.order_by("-assess_date", "-id").first()  # 含待定级
    return {
        "id": r.id,
        "name": r.name,
        "building": r.building,
        "room": r.room,
        "care_level": r.care_level,
        "care_level_display": r.get_care_level_display(),
        "diagnosis": r.diagnosis,
        "allergies": r.allergies,
        "assessment": _assessment_summary(latest_asmt),
        "logs_7d": [
            _log_out(log)
            for log in r.logs.filter(log_date__gte=since).order_by("-log_date", "-id")
        ],
        "health_records": [
            _health_out(h)
            for h in r.health_records.order_by("-record_date", "-id")[:30]
        ],
        "medications": [
            _medication_out(m)
            for m in r.medications.filter(is_active=True).order_by("id")
        ],
        "meal_orders_7d": [
            _format_order(o)
            for o in r.meal_orders.filter(date__gte=since)
            .prefetch_related("dishes").order_by("-date", "meal_type")
        ],
    }


# ---- 读：一周点餐视图 ----

@router.get("/meals/", response=dict)
def family_meals(request, week_start: str = ""):
    """代点餐页数据源：本周菜单 + 绑定老人该周全部订单（含已退，供改点）。"""
    fm = request.auth
    try:
        ws = date.fromisoformat(week_start) if week_start else date.today()
    except ValueError:
        raise HttpError(400, "week_start 须为 YYYY-MM-DD") from None
    ws = _monday(ws)  # 容错对齐周一
    end = ws + timedelta(days=6)
    menu = WeekMenu.objects.filter(week_start=ws).prefetch_related("dishes")
    orders = (
        MealOrder.objects.filter(resident_id__in=_bound_ids(fm), date__gte=ws, date__lte=end)
        .select_related("resident").prefetch_related("dishes")
        .order_by("date", "meal_type")
    )
    return {
        "week_start": str(ws),
        "week_end": str(end),
        "residents": [
            {"id": b.resident_id, "name": b.resident.name, "relation": b.get_relation_display()}
            for b in fm.bindings.select_related("resident").order_by("resident__id")
        ],
        "menu": [
            {
                "id": m.id,
                "week_start": str(m.week_start),
                "day": m.day,
                "meal_type": m.meal_type,
                "dishes": [
                    {"id": d.id, "name": d.name, "category": d.category}
                    for d in m.dishes.all()
                ],
            }
            for m in menu.order_by("day", "meal_type")
        ],
        "orders": [_format_order(o) for o in orders],
    }


# ---- 读：账单 ----

@router.get("/billing/", response=dict)
def family_billing(request, month: str = ""):
    """账单与欠费 — 复用 _bill_out 输出形状（与员工 /api/billing/ 同构，无 PII）。"""
    from billing.api import _bill_out

    fm = request.auth
    month = month or current_month()
    if not _MONTH_RE.match(month):
        raise HttpError(400, "month 须为 YYYY-MM")
    rows = []
    for b in fm.bindings.select_related("resident").order_by("resident__id"):
        bills = (
            MonthlyBill.objects.filter(resident=b.resident, month__lte=month)
            .select_related("resident").order_by("-month")
        )
        rows.append({
            "resident": {
                "id": b.resident_id,
                "name": b.resident.name,
                "relation": b.get_relation_display(),
            },
            "bills": [_bill_out(x) for x in bills],
            "arrears": _arrears_of(b.resident, month),
        })
    return {"month": month, "residents": rows}


# ---- 写：代点餐 / 退餐 ----

@router.post("/meal-orders/batch/", response=dict)
def family_meal_batch(request, payload: list[FamilyMealOrderIn]):
    """家属代点（整周）— 镜像员工批量：越权整批 403、防重整批 400，atomic 零残留。"""
    fm = request.auth
    for i, item in enumerate(payload):
        try:
            _resident_for_write(fm, item.resident_id)
        except HttpError as e:
            if e.status_code == 403:
                raise HttpError(403, f"第 {i + 1} 条越权，整批拒绝：{e.message}") from e
            raise
    _assert_no_active_duplicate(
        [(i.resident_id, i.date, i.meal_type) for i in payload], batch=True
    )
    created = 0
    with transaction.atomic():
        for item in payload:
            order = MealOrder.objects.create(
                resident_id=item.resident_id,
                date=item.date,
                meal_type=item.meal_type,
                special_requests=item.special_requests,
                ordered_by=_attribution(fm, item.resident_id),
            )
            order.dishes.set(item.dish_ids)
            created += 1
    names = list(Resident.objects.filter(
        id__in={i.resident_id for i in payload}).values_list("name", flat=True)[:5])
    record(request, action="家属代点餐",
           target=f"{created} 单（{'、'.join(names)}{'等' if len(names) == 5 else ''}）",
           target_model="meals.MealOrder")
    return {"status": "created", "count": created}


@router.post("/meal-orders/{order_id}/cancel/", response=dict)
def family_meal_cancel(request, order_id: int, payload: CancelIn | None = None):
    """家属代退 — 走真实 cancel() 留痕，changed_by 落家属归属串。"""
    fm = request.auth
    order = _order_for_write(fm, order_id)
    reason = (payload.reason if payload else "") or "家属代退"
    order.cancel(reason, operator=_attribution(fm, order.resident_id))
    record(request, action="家属退餐",
           target=f"{fm.name} 代 {order.resident.name} {order.date} {order.meal_type}",
           detail=f"原因：{reason}", target_model="meals.MealOrder", target_id=order.id)
    return {"id": order.id, "status": "cancelled"}
