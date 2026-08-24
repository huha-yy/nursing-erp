"""轻量专用页面 — 食堂看板 / 财务月结 / 周选点餐"""

from datetime import date, timedelta
from urllib.parse import urlencode

from nursing_erp.page_access import staff_required
from django.shortcuts import redirect, render

from assessments.models import Assessment, AssessmentItem, GradeLevelMap
from assessments.services import create_assessment, review_lists
from beds.services import occupancy_stats
from billing.models import MonthlyBill
from billing.services import arrears_stats, current_month, generate_month_bills, month_summary
from meals.models import MealFinance, MealOrder, WeekMenu
from residents.models import Resident


@staff_required
def kitchen_today(request):
    """食堂今日看板"""
    today = date.today()
    orders = MealOrder.objects.filter(date=today).select_related("resident").prefetch_related("dishes")

    breakfast = orders.filter(meal_type="早餐")
    lunch = orders.filter(meal_type="午餐")
    dinner = orders.filter(meal_type="晚餐")

    week_menu = WeekMenu.objects.filter(
        week_start__lte=today, week_start__gte=today - timedelta(days=7)
    ).prefetch_related("dishes")

    meal_data = [
        {"key": "早餐", "emoji": "🌅", "orders": breakfast,
         "menu": week_menu.filter(day=_day_of_week(today), meal_type="早餐").first()},
        {"key": "午餐", "emoji": "☀️", "orders": lunch,
         "menu": week_menu.filter(day=_day_of_week(today), meal_type="午餐").first()},
        {"key": "晚餐", "emoji": "🌙", "orders": dinner,
         "menu": week_menu.filter(day=_day_of_week(today), meal_type="晚餐").first()},
    ]

    total_orders = orders.count()
    cancel_count = orders.filter(status="cancelled").count()
    effective = total_orders - cancel_count

    return render(request, "kitchen_today.html", {
        "today": today,
        "meal_data": meal_data,
        "total_orders": total_orders,
        "cancel_count": cancel_count,
        "effective_orders": effective,
    })


@staff_required
def finance_monthly(request):
    """财务月度餐费对账"""
    month_param = request.GET.get("month", "")
    if not month_param:
        month_param = date.today().strftime("%Y-%m")

    records = MealFinance.objects.filter(month=month_param).select_related("resident")
    total_amount = sum(r.amount for r in records)
    total_paid = sum(r.amount for r in records if r.paid)
    total_unpaid = total_amount - total_paid

    return render(request, "finance_monthly.html", {
        "month": month_param,
        "records": records,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_unpaid": total_unpaid,
        "resident_count": records.count(),
        "paid_count": sum(1 for r in records if r.paid),
    })


@staff_required
def quick_log(request):
    """护理员快速录入"""
    return render(request, "quick_log.html")


@staff_required
def bed_board(request):
    """床位看板 — 入住率总览（与 /api/beds/occupancy/ 同源统计）"""
    stats = occupancy_stats(request.GET.get("building", "") or None)
    return render(request, "bed_board.html", {"stats": stats})


@staff_required
def billing_board(request):
    """应收月账单看板 — 出账 / 核销 / 欠费名单。

    与 /finance/ 同口径：登录即可见全院（无 session 楼栋强制——演示阶段楼长
    可见全院账单可接受，API 侧已有严格 scope，页面如需收紧再对齐）。
    """
    month = request.GET.get("month", "") or request.POST.get("month", "") or current_month()
    building = request.GET.get("building", "") or request.POST.get("building", "") or None

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "generate":
            generate_month_bills(month, building=building)
        elif action == "settle":
            bill = MonthlyBill.objects.filter(pk=request.POST.get("bill_id")).first()
            if bill:
                bill.settle(operator=_operator_name(request))
        query = f"month={month}"
        if building:
            query += f"&building={building}"
        return redirect(f"{request.path}?{query}")

    return render(request, "billing_board.html", {
        "month": month,
        "building": building or "",
        "summary": month_summary(month, building),
        "arrears": arrears_stats(month=month, building=building),
    })


def _operator_name(request) -> str:
    """核销人/定级人：session 员工姓名（无档案退回用户名）。"""
    try:
        return request.user.employee.name
    except Exception:
        return request.user.username


def _parse_date(s):
    try:
        return date.fromisoformat(s or "")
    except ValueError:
        return None


# 盘点表分页（周点餐同款交互，服务端切片——36 人量级足够）
_REVIEW_PAGE_SIZE = 20
_REVIEW_STATE_LABELS = {"pending": "待评估", "due": "待复评", "ok": "期内已评"}


@staff_required
def assessments_board(request):
    """入住评估看板 — 分页盘点 / 待定级确认 / 定级历史。

    录入已移至 /assessments/new/ 工作台（2026-08-24 交互改版：盘点表
    分页 + 状态筛选 + 姓名搜索，行尾进工作台）。建单/定级成功回本页
    toast（?created= / ?confirmed=）。
    与 /billing/ 同口径：登录即可见全院（无 session 楼栋强制——演示阶段可接受，
    API 侧已有严格 scope，页面如需收紧再对齐）。
    """
    error = ""
    if request.method == "POST" and request.POST.get("action") == "confirm":
        a = Assessment.objects.select_related("resident").filter(
            pk=request.POST.get("assessment_id", 0)
        ).first()
        if a is None:
            error = "评估单不存在"
        else:
            try:
                a.confirm(
                    operator=_operator_name(request),
                    final_level=request.POST.get("final_level", ""),
                    reason=request.POST.get("reason", ""),
                )
            except ValueError as exc:
                error = str(exc)
            if not error:
                return redirect("/assessments/?" + urlencode({"confirmed": a.resident.name}))

    # 三态合并成统一行集（待评估 → 待复评 → 期内，triage 置顶）再筛选/分页
    review = review_lists()
    rows = (
        [("pending", r) for r in review["pending_first"]]
        + [("due", r) for r in review["due_review"]]
        + [("ok", r) for r in review["ok"]]
    )
    state = request.GET.get("state", "")
    if state in _REVIEW_STATE_LABELS:
        rows = [row for row in rows if row[0] == state]
    q = request.GET.get("q", "").strip()
    if q:
        rows = [row for row in rows if q in row[1]["resident"].name]
    try:
        page_no = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page_no = 1
    pages = max(1, (len(rows) + _REVIEW_PAGE_SIZE - 1) // _REVIEW_PAGE_SIZE)
    page_no = min(page_no, pages)

    drafts = Assessment.objects.filter(
        status=Assessment.Status.DRAFT
    ).select_related("resident")
    history = Assessment.objects.filter(
        status=Assessment.Status.CONFIRMED
    ).select_related("resident")[:20]
    return render(request, "assessments_board.html", {
        "rows": rows[(page_no - 1) * _REVIEW_PAGE_SIZE: page_no * _REVIEW_PAGE_SIZE],
        "state_labels": _REVIEW_STATE_LABELS,
        "state": state,
        "q": q,
        "page_no": page_no,
        "pages": pages,
        "page_prev": page_no - 1,
        "page_next": page_no + 1,
        "row_total": len(rows),
        "counts": {
            "pending": len(review["pending_first"]),
            "due": len(review["due_review"]),
            "ok": len(review["ok"]),
        },
        "drafts": drafts,
        "history": history,
        "total_confirmed": Assessment.objects.filter(
            status=Assessment.Status.CONFIRMED
        ).count(),
        "care_levels": Resident.CareLevel.choices,
        "created": request.GET.get("created", ""),
        "confirmed": request.GET.get("confirmed", ""),
        "error": error,
    })


@staff_required
def assessment_form_page(request):
    """评估工作台 — 单人 26 项打分 + 实时总分角标（纯前端预览，落库以后端为准）。

    入口：看板盘点行「评估/复评」。无 resident_id / 老人不存在回看板。
    POST 建单失败原地回显（fail-loud），成功回看板 toast「已建单，待定级」。
    """
    resident = Resident.objects.filter(
        pk=request.GET.get("resident_id", 0)
    ).select_related("bed").first()
    if resident is None:
        return redirect("/assessments/")

    error = ""
    if request.method == "POST":
        assess_date = _parse_date(request.POST.get("assess_date", ""))
        scores: dict[int, int] = {}
        for key, value in request.POST.items():
            if key.startswith("score_") and value.strip():
                try:
                    scores[int(key[6:])] = int(value)
                except ValueError:
                    error = f"分值须为整数，收到：{value!r}"
                    break
        if assess_date is None:
            error = error or "评估日期格式须为 YYYY-MM-DD"
        if not error:
            try:
                a = create_assessment(
                    resident, assess_date,
                    request.POST.get("assessor1", ""), request.POST.get("assessor2", ""),
                    scores,
                )
                return redirect("/assessments/?" + urlencode({"created": a.resident.name}))
            except ValueError as exc:
                error = str(exc)  # fail-loud 回显，不跳转

    catalog = list(AssessmentItem.objects.filter(is_active=True))
    by_dim: dict[str, list] = {}
    for item in catalog:
        by_dim.setdefault(item.dimension, []).append(item)
    groups = [
        {"dimension": AssessmentItem.Dimension(dim).label, "items": items}
        for dim, items in by_dim.items()
    ]
    last = resident.assessments.filter(
        status=Assessment.Status.CONFIRMED
    ).order_by("-assess_date").first()
    # 角标预览数据（json_script 注入）：分段/等级标签是国标常量，映射读配置表
    # ——后台改映射前端无需跟改。仅预览；总分落库仍以 recalculate() 为准。
    badge = {
        "total_max": sum(i.max_score for i in catalog),
        "bands": Assessment.BANDS,
        "labels": {str(k): v for k, v in Assessment.GRADE_LABELS.items()},
        "level_map": {str(m.grade): m.care_level for m in GradeLevelMap.objects.all()},
    }
    return render(request, "assessment_form.html", {
        "resident": resident,
        "groups": groups,
        "last": last,
        "badge": badge,
        "error": error,
    })


@staff_required
def assessment_detail_page(request, assessment_id):
    """评估单详情（只读）— 26 项打分明细 + 定级信息。

    入口：看板「定级历史/待定级」行「详情 ›」、工作台「上次评估」链接。
    不存在回看板（与 API 的 404 语义不同：页面侧统一回列表）。
    """
    a = (
        Assessment.objects.select_related("resident")
        .prefetch_related("scores__item")
        .filter(pk=assessment_id)
        .first()
    )
    if a is None:
        return redirect("/assessments/")
    by_dim: dict[str, list] = {}
    for s in sorted(a.scores.all(), key=lambda s: s.item.order):
        by_dim.setdefault(s.item.dimension, []).append(s)
    groups = [
        {
            "dimension": AssessmentItem.Dimension(dim).label,
            "rows": [
                {
                    "name": s.item.name, "score": s.score, "max": s.item.max_score,
                    # 0-10/0-5 量表 ×100 恒整（10 的倍数/20 的倍数）
                    "pct": s.score * 100 // s.item.max_score,
                }
                for s in rows
            ],
            "subtotal": sum(s.score for s in rows),
            "subtotal_max": sum(s.item.max_score for s in rows),
        }
        for dim, rows in by_dim.items()
    ]
    return render(request, "assessment_detail.html", {
        "a": a,
        "grade_label": Assessment.GRADE_LABELS[a.grade],
        "groups": groups,
    })


@staff_required
def weekly_order(request):
    """周五周选点餐 — 护理员帮老人选下周菜品"""
    return render(request, "weekly_order.html")


@staff_required
def menu_ocr_page(request):
    """食堂菜单 OCR 录入 — 拍照自动识别菜品"""
    return render(request, "menu_ocr.html")


@staff_required
def meal_order_ocr_page(request):
    """老人点餐 OCR 录入 — 选老人 + 拍照自动识别点餐单"""
    return render(request, "meal_order_ocr.html")


def _day_of_week(d):
    """date → 周一/周二/..."""
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return days[d.weekday()]


@staff_required
def resident_lifecycle(request, resident_id):
    """老人全生命周期档案 — 时间线 + 健康趋势"""
    from django.shortcuts import get_object_or_404

    from residents.models import Resident

    resident = get_object_or_404(Resident, id=resident_id)

    events = []

    COLORS = {
        "入住": "#27ae60", "护理": "#3b82f6", "健康": "#14b8a6", "用药": "#8b5cf6",
        "作息": "#94a3b8", "异常": "#ef4444", "等级变更": "#f59e0b", "转区": "#f59e0b",
        "评估": "#0ea5e9", "离院": "#6b7280",
    }

    def add(d, kind, icon, title, detail=""):
        if d:
            events.append({
                "date": d, "kind": kind, "icon": icon, "title": title,
                "detail": detail or "", "color": COLORS.get(kind, "#6b7280"),
            })

    # 入住（时间线起点）
    add(resident.admission_date, "入住", "🏠", "入住",
        f"{resident.building} {resident.floor} {resident.room}室 · 初始等级 {resident.get_care_level_display()}")

    for o in resident.logs.all():
        add(o.log_date, "护理", "🛏️", o.get_category_display(), o.detail)

    for o in resident.health_records.all():
        add(o.record_date, "健康", "❤️",
            f"血压 {o.blood_pressure or '—'} · 心率 {o.heart_rate or '—'}", o.note)

    for o in resident.medications.all():
        add(o.start_date, "用药", "💊", o.medicine_name, f"{o.dosage} · {o.get_frequency_display()}")

    for o in resident.routines.all():
        add(o.log_date, "作息", "🕐", f"情绪 {o.mood or '—'}", o.activities)

    for o in resident.incidents.all():
        add(o.created_at.date(), "异常", "⚠️", o.get_category_display(), o.description)

    for o in resident.level_changes.all():
        add(o.change_date, "等级变更", "📈",
            f"{o.get_from_level_display()} → {o.get_to_level_display()}", o.reason)

    for o in resident.assessments.all():
        add(o.assess_date, "评估", "📋",
            f"能力评估 {o.total_score}分·{Assessment.GRADE_LABELS[o.grade]}",
            f"评估员 {o.assessor1}/{o.assessor2}"
            + (f"·定级 {o.final_level}" if o.final_level else "·待定级"))

    for o in resident.transfers.all():
        add(o.transfer_date, "转区", "🚚",
            f"{o.get_from_zone_display()} → {o.get_to_zone_display()}", o.reason)

    for o in resident.discharges.all():
        add(o.discharge_date, "离院", "🏠", o.get_discharge_type_display(), o.reason)

    events.sort(key=lambda e: e["date"], reverse=True)
    for e in events:
        e["date"] = e["date"].strftime("%Y-%m-%d")

    # 健康趋势（血压收缩/舒张、血糖、体重）— 连续日期轴，缺失日期补 None
    hrs = list(resident.health_records.order_by("record_date"))
    by_date = {h.record_date: h for h in hrs}
    dates, bp_sys, bp_dia, bs, wt = [], [], [], [], []
    if hrs:
        cur, end = hrs[0].record_date, hrs[-1].record_date
        while cur <= end:
            dates.append(cur.strftime("%m-%d"))
            h = by_date.get(cur)
            if h:
                s = d = None
                if h.blood_pressure and "/" in h.blood_pressure:
                    try:
                        s, d = (int(x) for x in h.blood_pressure.split("/"))
                    except ValueError:
                        s = d = None
                bp_sys.append(s)
                bp_dia.append(d)
                bs.append(float(h.blood_sugar) if h.blood_sugar is not None else None)
                wt.append(float(h.weight) if h.weight is not None else None)
            else:
                bp_sys.append(None)
                bp_dia.append(None)
                bs.append(None)
                wt.append(None)
            cur += timedelta(days=1)

    trend = {"dates": dates, "bp_sys": bp_sys, "bp_dia": bp_dia, "blood_sugar": bs, "weight": wt}

    return render(request, "resident_lifecycle.html", {
        "page_title": f"{resident.name} 生命周期档案",
        "resident": resident,
        "events": events,
        "trend": trend,
    })
