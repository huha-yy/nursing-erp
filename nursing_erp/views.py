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
