"""轻量专用页面 — 食堂看板 / 财务月结 / 周选点餐"""

from datetime import date, timedelta

from django.shortcuts import render

from meals.models import MealOrder, WeekMenu, MealFinance


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


def quick_log(request):
    """护理员快速录入"""
    return render(request, "quick_log.html")


def weekly_order(request):
    """周五周选点餐 — 护理员帮老人选下周菜品"""
    return render(request, "weekly_order.html")


def menu_ocr_page(request):
    """食堂菜单 OCR 录入 — 拍照自动识别菜品"""
    return render(request, "menu_ocr.html")


def meal_order_ocr_page(request):
    """老人点餐 OCR 录入 — 选老人 + 拍照自动识别点餐单"""
    return render(request, "meal_order_ocr.html")


def _day_of_week(d):
    """date → 周一/周二/..."""
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return days[d.weekday()]


def resident_lifecycle(request, resident_id):
    """老人全生命周期档案 — 时间线 + 健康趋势"""
    from django.shortcuts import get_object_or_404

    from residents.models import Resident

    resident = get_object_or_404(Resident, id=resident_id)

    events = []

    COLORS = {
        "入住": "#27ae60", "护理": "#3b82f6", "健康": "#14b8a6", "用药": "#8b5cf6",
        "作息": "#94a3b8", "异常": "#ef4444", "等级变更": "#f59e0b", "转区": "#f59e0b",
        "离院": "#6b7280",
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
