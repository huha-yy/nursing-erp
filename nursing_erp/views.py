"""轻量专用页面 — 食堂看板 / 财务月结

这些页面面向非管理角色：
- /kitchen/   食堂：今日点餐汇总，不需要登录
- /finance/   财务：月度餐费对账
"""

from datetime import date

from django.shortcuts import render

from meals.models import MealOrder, MealPlan, MealFinance


def kitchen_today(request):
    """食堂今日看板 — 显示三餐点餐数量和特殊需求"""
    today = date.today()
    orders = MealOrder.objects.filter(date=today).select_related("resident")

    # 按餐次统计
    breakfast = orders.filter(meal_type="早餐")
    lunch = orders.filter(meal_type="午餐")
    dinner = orders.filter(meal_type="晚餐")

    # 今日菜单
    menus = MealPlan.objects.filter(date=today)

    # 按餐次组织数据，方便模板遍历
    meal_data = [
        {"key": "早餐", "emoji": "🌅", "orders": breakfast, "menu": menus.filter(meal_type="早餐").first()},
        {"key": "午餐", "emoji": "☀️", "orders": lunch, "menu": menus.filter(meal_type="午餐").first()},
        {"key": "晚餐", "emoji": "🌙", "orders": dinner, "menu": menus.filter(meal_type="晚餐").first()},
    ]

    total_orders = orders.count()
    cancel_count = orders.filter(status="cancelled").count()
    effective = total_orders - cancel_count

    context = {
        "today": today,
        "meal_data": meal_data,
        "total_orders": total_orders,
        "cancel_count": cancel_count,
        "effective_orders": effective,
    }
    return render(request, "kitchen_today.html", context)


def finance_monthly(request):
    """财务月度餐费对账"""
    month_param = request.GET.get("month", "")
    if not month_param:
        month_param = date.today().strftime("%Y-%m")

    records = MealFinance.objects.filter(month=month_param).select_related("resident")
    total_amount = sum(r.amount for r in records)
    total_paid = sum(r.amount for r in records if r.paid)
    total_unpaid = total_amount - total_paid

    context = {
        "month": month_param,
        "records": records,
        "total_amount": total_amount,
        "total_paid": total_paid,
        "total_unpaid": total_unpaid,
        "resident_count": records.count(),
        "paid_count": sum(1 for r in records if r.paid),
    }
    return render(request, "finance_monthly.html", context)


def quick_log(request):
    """护理员快速录入 — 手机端极简页面"""
    return render(request, "quick_log.html")
