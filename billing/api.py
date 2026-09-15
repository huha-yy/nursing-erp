"""应收月账单 API — dl-control 财务技能与 /billing/ 看板的后端。

楼栋守卫：列表/汇总/欠费/核销走 scope（X-Building 头或 session 档案）；
generate 不按调用方范围收窄（财务出账是全院口径，对齐既有
/api/meal-finance/generate/ 的做法）。
"""

import re
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils.translation import gettext as _n
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from auditlog.record import record
from nursing_erp.api_scope import resolve_building_scope, scope_filter

from .models import MonthlyBill
from .services import current_month, generate_month_bills

router = Router(tags=["应收账单"])

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class SettleIn(Schema):
    """核销入参 — settled_by 缺省取 session 员工名/用户名（key 路径为 "api"）。"""
    note: str = ""
    settled_by: str = ""


def _bill_out(b: MonthlyBill) -> dict:
    return {
        "id": b.id,
        "resident_id": b.resident_id,
        "resident_name": b.resident.name,
        "building": b.resident.building,
        "room": b.resident.room,
        "month": b.month,
        "bed_fee": float(b.bed_fee),
        "nursing_fee": float(b.nursing_fee),
        "meal_fee": float(b.meal_fee),
        "total": float(b.total),
        "status": b.status,
        "status_display": b.get_status_display(),
        "settled_at": b.settled_at.isoformat() if b.settled_at else None,
        "settled_by": b.settled_by,
        "note": b.note,
    }


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


def _bill_for_write(request, bill_id: int) -> MonthlyBill:
    """核销守卫（照抄 meals cancel 模式）：缺失 404 / 跨楼 403。"""
    bill = MonthlyBill.objects.select_related("resident").filter(pk=bill_id).first()
    if bill is None:
        raise HttpError(404, _n("账单不存在"))
    scope = resolve_building_scope(request)
    if scope and bill.resident.building != scope:
        raise HttpError(
            403,
            _n("无权操作 {} 的账单（当前范围：{}）").format(bill.resident.building, scope),
        )
    return bill


# ---- 列表 / 汇总 / 欠费 ----


@router.get("/billing/", response=list[dict])
@paginate(PageNumberPagination, page_size=50)
def list_bills(request, month: str = "", status: str = ""):
    qs = MonthlyBill.objects.select_related("resident").all()
    if month:
        qs = qs.filter(month=month)
    if status:
        qs = qs.filter(status=status)
    qs = scope_filter(qs, request, "resident__building")
    return [_bill_out(b) for b in qs]


@router.get("/billing/summary/", response=dict)
def billing_summary(request, month: str = ""):
    """单月三额勾稽（scope 生效）。"""
    month = month or current_month()
    qs = MonthlyBill.objects.filter(month=month)
    qs = scope_filter(qs, request, "resident__building")
    agg = qs.aggregate(
        count=Count("id"),
        paid_count=Count("id", filter=Q(status=MonthlyBill.Status.PAID)),
        receivable=Sum("total"),
        received=Sum("total", filter=Q(status=MonthlyBill.Status.PAID)),
    )
    receivable = agg["receivable"] or Decimal("0")
    received = agg["received"] or Decimal("0")
    return {
        "month": month,
        "count": agg["count"],
        "paid_count": agg["paid_count"],
        "receivable": float(receivable),
        "received": float(received),
        "outstanding": float(receivable - received),
    }


@router.get("/billing/arrears/", response=dict)
def billing_arrears(request, month: str = ""):
    """欠费名单（截止 month，含更早账期；scope 生效）。"""
    from .services import arrears_stats

    cutoff = month or current_month()
    arrears = arrears_stats(month=cutoff, building=resolve_building_scope(request))
    return {
        "month": arrears["month"],
        "resident_count": arrears["resident_count"],
        "total_outstanding": float(arrears["total_outstanding"]),
        "rows": [
            {
                "resident_id": r["resident_id"],
                "resident_name": r["resident__name"],
                "building": r["resident__building"],
                "room": r["resident__room"],
                "unpaid_months": r["unpaid_months"],
                "oldest_month": r["oldest_month"],
                "outstanding": float(r["outstanding"]),
            }
            for r in arrears["rows"]
        ],
    }


# ---- 生成 / 核销 ----


@router.post("/billing/generate/", response=dict)
def generate_bills(
    request,
    month: str,
    building: str = "",
    resident_id: int | None = None,
):
    """生成月账单（财务全院口径，不按调用方楼栋范围收窄——见模块 docstring）。"""
    if not _MONTH_RE.match(month or ""):
        raise HttpError(400, _n("month 格式须为 YYYY-MM，收到：{!r}").format(month))
    rv = generate_month_bills(month, resident_id=resident_id, building=building or None)
    record(request, action="账单生成",
           target=f"{month}{' · ' + building if building else ''}"
                  f"{' · 指定老人' if resident_id else ''}",
           detail=f"出账 {rv['generated']} 单（含刷新），已核销跳过 {rv['skipped_paid']} 单",
           target_model="billing.MonthlyBill")
    return rv


@router.post("/billing/{bill_id}/settle/", response=dict)
def settle_bill(request, bill_id: int, payload: SettleIn | None = None):
    """全额核销（幂等）。"""
    bill = _bill_for_write(request, bill_id)
    payload = payload or SettleIn()
    operator = _operator_name(request, payload.settled_by)
    already = bill.status == MonthlyBill.Status.PAID
    bill.settle(operator=operator, note=payload.note)
    record(request, action="账单核销",
           target=f"{bill.resident.name}（{bill.resident.building}{bill.resident.room}）"
                  f"{bill.month} ¥{bill.total}",
           detail=(f"重复核销（幂等命中） · 经手人：{bill.settled_by}"
                   if already else f"经手人：{operator}"
                   + (f" · 备注：{payload.note}" if payload.note else "")),
           target_model="billing.MonthlyBill", target_id=bill.id,
           actor_name=operator)  # 署名可能经 dl-control 转发：台账查到记员工，查不到记 AI
    return _bill_out(bill)


@router.post("/billing/{bill_id}/unsettle/", response=dict)
def unsettle_bill(request, bill_id: int):
    """撤销核销（幂等）——回 pending 后可再生成刷新金额。"""
    bill = _bill_for_write(request, bill_id)
    was_paid = bill.status == MonthlyBill.Status.PAID
    prev_by = bill.settled_by
    bill.unsettle()
    record(request, action="撤销核销",
           target=f"{bill.resident.name}（{bill.resident.building}{bill.resident.room}）"
                  f"{bill.month} ¥{bill.total}",
           detail=(f"原核销人：{prev_by}" if was_paid else "重复撤销（幂等命中，本就是待收）"),
           target_model="billing.MonthlyBill", target_id=bill.id)
    return _bill_out(bill)
