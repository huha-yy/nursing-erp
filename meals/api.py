from typing import List, Optional
from datetime import date

from ninja import Router, Query
from ninja.pagination import paginate, PageNumberPagination

from .models import MealPlan, MealOrder, MealFinance

router = Router(tags=["点餐送餐"])


@router.get("/meal-plans/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_meal_plans(
    request,
    date_param: Optional[date] = Query(None, alias="date", description="日期"),
):
    qs = MealPlan.objects.all()
    if date_param:
        qs = qs.filter(date=date_param)
    return [
        {"id": p.id, "date": str(p.date), "meal_type": p.meal_type,
         "menu_items": p.menu_items}
        for p in qs
    ]


@router.get("/meal-orders/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_meal_orders(
    request,
    date_param: Optional[date] = Query(None, alias="date", description="日期"),
    status: Optional[str] = Query(None, description="状态"),
    meal_type: Optional[str] = Query(None, description="餐次"),
):
    qs = MealOrder.objects.select_related("resident").all()
    if date_param:
        qs = qs.filter(date=date_param)
    if status:
        qs = qs.filter(status=status)
    if meal_type:
        qs = qs.filter(meal_type=meal_type)
    return [
        {
            "id": o.id, "resident_name": o.resident.name,
            "building": o.resident.building, "room": o.resident.room,
            "date": str(o.date), "meal_type": o.meal_type,
            "menu_choice": o.menu_choice, "special_requests": o.special_requests,
            "status": o.status, "status_display": o.get_status_display(),
            "ordered_by": o.ordered_by,
        }
        for o in qs
    ]


@router.get("/meal-finance/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_meal_finance(
    request,
    month: Optional[str] = Query(None, description="月份 如2026-08"),
):
    qs = MealFinance.objects.select_related("resident").all()
    if month:
        qs = qs.filter(month=month)
    return [
        {"id": f.id, "resident_name": f.resident.name,
         "month": f.month, "total_meals": f.total_meals,
         "cancelled": f.cancelled, "amount": float(f.amount),
         "paid": f.paid}
        for f in qs
    ]
