from typing import List, Optional
from datetime import date, timedelta
import base64, os, re

from ninja import Router, Query, Schema
from ninja.pagination import paginate, PageNumberPagination

from .models import Dish, WeekMenu, MealOrder, MealFinance

router = Router(tags=["点餐送餐"])


# ---- Schemas ----

class MealOrderIn(Schema):
    """创建/更新点餐订单 — 护理员勾选菜品"""
    resident_id: int
    date: str  # "2026-08-11"
    meal_type: str  # 早餐/午餐/晚餐
    dish_ids: list[int]
    special_requests: str = ""
    ordered_by: str = ""


# ---- Dish ----

@router.get("/dishes/", response=List[dict])
def list_dishes(request):
    """菜品库"""
    return [
        {"id": d.id, "name": d.name, "category": d.category, "is_available": d.is_available}
        for d in Dish.objects.filter(is_available=True)
    ]


# ---- WeekMenu ----

@router.get("/week-menu/", response=List[dict])
def list_week_menu(request, week_start: Optional[str] = Query(None, description="周一日期, 如2026-08-10")):
    """本周菜单 — 每天每餐可选菜品列表"""
    qs = WeekMenu.objects.filter(week_start=week_start).prefetch_related("dishes")
    return [
        {
            "id": m.id, "week_start": str(m.week_start),
            "day": m.day, "meal_type": m.meal_type,
            "dishes": [{"id": d.id, "name": d.name, "category": d.category}
                       for d in m.dishes.all()]
        }
        for m in qs
    ]


# ---- MealOrder ----

@router.get("/meal-orders/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_meal_orders(
    request,
    date_param: Optional[date] = Query(None, alias="date", description="日期"),
    status: Optional[str] = Query(None, description="状态"),
    meal_type: Optional[str] = Query(None, description="餐次"),
    resident_id: Optional[int] = Query(None, description="老人ID"),
):
    qs = MealOrder.objects.select_related("resident").prefetch_related("dishes").all()
    if date_param:
        qs = qs.filter(date=date_param)
    if status:
        qs = qs.filter(status=status)
    if meal_type:
        qs = qs.filter(meal_type=meal_type)
    if resident_id:
        qs = qs.filter(resident_id=resident_id)
    return [_format_order(o) for o in qs]


@router.post("/meal-orders/", response=dict)
def create_meal_order(request, payload: MealOrderIn):
    """创建点餐订单 — 常用于周五批量点餐"""
    order = MealOrder.objects.create(
        resident_id=payload.resident_id,
        date=payload.date,
        meal_type=payload.meal_type,
        special_requests=payload.special_requests,
        ordered_by=payload.ordered_by,
    )
    order.dishes.set(payload.dish_ids)
    return {"id": order.id, "status": "created"}


@router.post("/meal-orders/batch/", response=dict)
def create_meal_orders_batch(request, payload: list[MealOrderIn]):
    """批量创建 — 护理员帮老人一次性点整周"""
    created = 0
    for item in payload:
        order = MealOrder.objects.create(
            resident_id=item.resident_id,
            date=item.date,
            meal_type=item.meal_type,
            special_requests=item.special_requests,
            ordered_by=item.ordered_by,
        )
        order.dishes.set(item.dish_ids)
        created += 1
    return {"status": "created", "count": created}


@router.post("/meal-orders/{order_id}/cancel/", response=dict)
def cancel_meal_order(request, order_id: int, reason: str = ""):
    """退餐"""
    order = MealOrder.objects.get(id=order_id)
    order.cancel(reason)
    return {"id": order.id, "status": "cancelled"}


# ---- MealFinance ----

@router.get("/meal-finance/", response=List[dict])
@paginate(PageNumberPagination, page_size=50)
def list_meal_finance(request, month: Optional[str] = Query(None, description="月份 如2026-08")):
    qs = MealFinance.objects.select_related("resident").all()
    if month:
        qs = qs.filter(month=month)
    return [{
        "id": f.id, "resident_name": f.resident.name,
        "month": f.month, "total_meals": f.total_meals,
        "cancelled": f.cancelled, "amount": float(f.amount), "paid": f.paid,
    } for f in qs]


@router.post("/meal-finance/generate/", response=dict)
def generate_meal_finance(request, month: str, resident_id: int | None = None):
    """生成月度餐费对账单"""
    from residents.models import Resident
    qs = Resident.objects.all()
    if resident_id:
        qs = qs.filter(id=resident_id)
    count = 0
    for resident in qs:
        MealFinance.generate_monthly(resident, month)
        count += 1
    return {"status": "generated", "count": count}


# ---- Helper ----

def _format_order(o: MealOrder) -> dict:
    return {
        "id": o.id,
        "resident_name": o.resident.name,
        "building": o.resident.building,
        "room": o.resident.room,
        "date": str(o.date),
        "meal_type": o.meal_type,
        "dishes": [{"id": d.id, "name": d.name, "category": d.category}
                   for d in o.dishes.all()],
        "special_requests": o.special_requests,
        "status": o.status,
        "status_display": o.get_status_display(),
        "ordered_by": o.ordered_by,
    }


# ---- OCR: menu photo → dish matching ----

class MenuOcrIn(Schema):
    image: str  # base64

class MenuOcrOut(Schema):
    text: str
    matches: list[dict]  # [{line, suggestions: [{id, name, score}]}]


@router.post("/menu-ocr/", response=dict)
def menu_ocr(request, payload: MenuOcrIn):
    """识别菜单照片 → 匹配菜品库"""
    ocr_text = ""
    try:
        import httpx
        ocr_url = os.environ.get("DL_OCR_URL", "http://192.168.10.247:18080")
        ocr_token = os.environ.get("DL_OCR_API_TOKEN", "")
        headers = {"Authorization": f"Bearer {ocr_token}"} if ocr_token else {}
        r = httpx.post(f"{ocr_url}/v1/ocr", json={"image": payload.image},
                       headers=headers, timeout=120)
        if r.status_code == 200:
            ocr_text = r.json().get("text", "").strip()
    except Exception:
        pass

    # Match each line against Dish library
    dishes = list(Dish.objects.filter(is_available=True).values("id", "name", "category"))
    matches = []
    for line in ocr_text.split("\n"):
        line = line.strip()
        if len(line) < 2:
            continue
        # Skip common non-dish lines
        if re.match(r'^(周一|周二|周三|周四|周五|周六|周日|早餐|午餐|晚餐|星期|菜谱|菜单|[0-9./\-]+)$', line):
            matches.append({"line": line, "suggestions": []})
            continue
        suggestions = []
        for d in dishes:
            score = _fuzzy_match(line, d["name"])
            if score > 0.3:
                suggestions.append({"id": d["id"], "name": d["name"],
                                    "category": d["category"], "score": round(score, 2)})
        suggestions.sort(key=lambda x: x["score"], reverse=True)
        matches.append({"line": line, "suggestions": suggestions[:5]})

    return {"text": ocr_text, "matches": matches, "dish_count": len(dishes)}


@router.post("/menu-ocr/batch-create/", response=dict)
def menu_ocr_batch_create(request, payload: list[dict]):
    """根据 OCR 匹配结果批量创建周菜单"""
    created = 0
    for item in payload:
        dish_ids = item.get("dish_ids", [])
        day = item.get("day", "")
        meal_type = item.get("meal_type", "")
        week_start = item.get("week_start", "")
        if not dish_ids or not day or not meal_type or not week_start:
            continue
        menu, _ = WeekMenu.objects.get_or_create(
            week_start=week_start, day=day, meal_type=meal_type)
        menu.dishes.set(dish_ids)
        created += 1
    return {"status": "created", "count": created}


def _fuzzy_match(text: str, target: str) -> float:
    """Simple fuzzy match score between text and target dish name."""
    if target in text:
        return 0.95
    # Character overlap score
    t_chars = set(text)
    overlap = sum(1 for c in target if c in t_chars)
    return overlap / max(len(target), 1)
