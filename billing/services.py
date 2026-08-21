"""账单聚合与批量出账 — /api/billing/* 与 /billing/ 看板共用同一份数学（仿 beds/services.py）。"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Min, Q, Sum

from residents.models import Resident

from .models import MonthlyBill


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def generate_month_bills(
    month: str, resident_id: int | None = None, building: str | None = None
) -> dict:
    """批量生成月账单。

    范围 = 在住(bed 非空) ∪ 当月有餐费月结行 ∪ 当月有点餐 —— 无床老人当月
    有餐费时也要能出收尾账单。transaction.atomic 包裹：价目缺行 fail-loud
    时整批回滚，不留半批。36 人量级逐条生成即可。
    """
    qs = Resident.objects.filter(
        Q(bed__isnull=False)
        | Q(meal_finances__month=month)
        | Q(meal_orders__date__startswith=month)
    ).distinct()
    if resident_id:
        qs = qs.filter(id=resident_id)
    if building:
        qs = qs.filter(building=building)

    generated = skipped_paid = 0
    total = Decimal("0")
    with transaction.atomic():
        for resident in qs.order_by("id"):
            bill = MonthlyBill.generate_month(resident, month)
            # generate_month 只会把"本轮前已 paid"的账单以 paid 状态返回（冻结），
            # 新建/刷新的恒为 pending——status 即可区分两种计数
            if bill.status == MonthlyBill.Status.PAID:
                skipped_paid += 1
            else:
                generated += 1
            total += bill.total
    return {
        "month": month,
        "generated": generated,
        "skipped_paid": skipped_paid,
        "total": total,
    }


def month_summary(month: str, building: str | None = None) -> dict:
    """单月汇总：逐单明细 + 应收/已收/欠缴三额。"""
    qs = MonthlyBill.objects.filter(month=month).select_related("resident")
    if building:
        qs = qs.filter(resident__building=building)
    bills = list(qs)
    receivable = sum((b.total for b in bills), Decimal("0"))
    received = sum(
        (b.total for b in bills if b.status == MonthlyBill.Status.PAID), Decimal("0")
    )
    return {
        "month": month,
        "bills": bills,
        "receivable": receivable,
        "received": received,
        "outstanding": receivable - received,
        "paid_count": sum(1 for b in bills if b.status == MonthlyBill.Status.PAID),
    }


def arrears_stats(month: str | None = None, building: str | None = None) -> dict:
    """欠费名单 — 截止某月的全部待缴费账单按老人聚合。

    month 截止参数（YYYY-MM 定长，字典序=时间序）；None=当月。
    """
    month = month or current_month()
    qs = MonthlyBill.objects.filter(status=MonthlyBill.Status.PENDING, month__lte=month)
    if building:
        qs = qs.filter(resident__building=building)
    rows = list(
        qs.values("resident_id", "resident__name", "resident__building", "resident__room")
        .annotate(
            unpaid_months=Count("id"),
            outstanding=Sum("total"),
            oldest_month=Min("month"),
        )
        .order_by("-outstanding", "resident__name")
    )
    return {
        "month": month,
        "rows": rows,
        "resident_count": len(rows),
        "total_outstanding": sum((r["outstanding"] for r in rows), Decimal("0")),
    }
