from typing import List, Optional
from datetime import date, timedelta
import base64, os, re, json

from ninja import Router, Query, Schema
from ninja.pagination import paginate, PageNumberPagination

from .models import Dish, WeekMenu, MealOrder, MealFinance
from nursing_erp.llm import chat as llm_chat

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
    image: str = ""  # 单张 base64（向后兼容）
    images: list[str] = []  # 多张 base64（跨页菜单）


@router.post("/menu-ocr/", response=dict)
def menu_ocr(request, payload: MenuOcrIn):
    """识别菜单照片（支持多张跨页）→ OCR 提取文字 → LLM 结构化纠错 → 匹配菜品库。

    返回结构化的每天每餐菜名列表（LLM 自动识别星期/餐次，并纠正错别字
    对齐到菜品库标准名），而非逐行文字。
    """
    # 1. OCR 提取原始文字（支持多张跨页）
    images = payload.images or ([payload.image] if payload.image else [])
    ocr_text = _ocr_extract_multi(images)
    if not ocr_text:
        return {"error": "OCR 未识别到文字", "structured": {}, "unmatched": []}

    # 2. LLM 结构化 + 纠错
    dish_names = list(Dish.objects.filter(is_available=True).values_list("name", flat=True))
    structured = _llm_structure_menu(ocr_text, dish_names)

    # 3. 每个菜名匹配菜品库拿 dish_id
    dishes_by_name = {d.name: d.id for d in Dish.objects.filter(is_available=True)}
    result = {}
    unmatched = []
    for day, meals in structured.items():
        result[day] = {}
        for meal_type, names in meals.items():
            result[day][meal_type] = []
            for name in names:
                name = name.strip()
                if not name:
                    continue
                # 精确匹配菜品库
                dish_id = dishes_by_name.get(name)
                if dish_id:
                    result[day][meal_type].append({"name": name, "dish_id": dish_id, "matched": True})
                else:
                    # 尝试整词容错匹配
                    best_id, best_name = _find_best_dish(name, dishes_by_name)
                    if best_id:
                        result[day][meal_type].append({"name": best_name, "dish_id": best_id, "matched": True})
                    else:
                        result[day][meal_type].append({"name": name, "dish_id": None, "matched": False})
                        unmatched.append(name)

    return {"text": ocr_text, "structured": result, "unmatched": unmatched,
            "dish_count": len(dishes_by_name)}


@router.post("/menu-ocr/batch-create/", response=dict)
def menu_ocr_batch_create(request, payload: list[dict]):
    """根据结构化识别结果批量创建周菜单。"""
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


# ---- 老人点餐 OCR ----

class MealOrderOcrIn(Schema):
    image: str = ""  # 单张 base64（向后兼容）
    images: list[str] = []  # 多张 base64（跨页）


@router.post("/meal-order-ocr/", response=dict)
def meal_order_ocr(request, payload: MealOrderOcrIn):
    """识别老人点餐单照片（支持多张跨页）→ 结构化（含特殊要求）→ 匹配菜品库。"""
    images = payload.images or ([payload.image] if payload.image else [])
    ocr_text = _ocr_extract_multi(images)
    if not ocr_text:
        return {"error": "OCR 未识别到文字", "structured": {}, "unmatched": []}

    dish_names = list(Dish.objects.filter(is_available=True).values_list("name", flat=True))
    raw = _llm_structure(ocr_text, dish_names, mode="order")

    dishes_by_name = {d.name: d.id for d in Dish.objects.filter(is_available=True)}
    result = {}
    unmatched = []
    for day, meals in raw.items():
        result[day] = {}
        for meal_type, names in meals.items():
            result[day][meal_type] = []
            for name in names:
                parsed = _parse_order_item(name)  # → (dish_name, note)
                dish_name, note = parsed
                if dish_name:  # 有菜名
                    dish_id = dishes_by_name.get(dish_name)
                    if not dish_id:
                        best_id, best_name = _find_best_dish(dish_name, dishes_by_name)
                        if best_id:
                            dish_id, dish_name = best_id, best_name
                    result[day][meal_type].append(
                        {"name": dish_name, "note": note, "dish_id": dish_id,
                         "matched": dish_id is not None})
                    if dish_id is None:
                        unmatched.append(dish_name)
                else:  # 纯特殊要求（如"不吃"）
                    result[day][meal_type].append(
                        {"name": "", "note": note, "dish_id": None, "matched": False})

    return {"text": ocr_text, "structured": result, "unmatched": unmatched,
            "dish_count": len(dishes_by_name)}


@router.post("/meal-order-ocr/batch-create/", response=dict)
def meal_order_ocr_batch_create(request, payload: list[dict]):
    """根据老人点餐识别结果批量创建 MealOrder。"""
    from residents.models import Resident

    resident_id = payload[0].get("resident_id") if payload else None
    created = 0
    day_index = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6}
    for item in payload:
        resident_id = item.get("resident_id", resident_id)
        dish_ids = item.get("dish_ids", [])
        day = item.get("day", "")
        meal_type = item.get("meal_type", "")
        week_start = item.get("week_start", "")
        special_requests = item.get("special_requests", "")
        if not resident_id or not day or not meal_type or not week_start:
            continue
        # 只有特殊要求没有菜（如"不吃"），也记录一条
        if not dish_ids and not special_requests:
            continue
        # 计算就餐日期（周一=week_start，周日起+6天）
        base = date.fromisoformat(week_start)
        order_date = base + timedelta(days=day_index.get(day, 0))
        order = MealOrder.objects.create(
            resident_id=resident_id, date=order_date, meal_type=meal_type,
            special_requests=special_requests,
        )
        if dish_ids:
            order.dishes.set(dish_ids)
        created += 1
    return {"status": "created", "count": created}


def _parse_order_item(name: str) -> tuple:
    """解析 LLM 输出的菜名，分离括号特殊要求。返回 (菜名, 特殊要求)。

    如 "清蒸鲈鱼(少盐)" → ("清蒸鲈鱼", "少盐")；"不吃(外出)" → ("", "不吃(外出)")。
    """
    name = name.strip()
    m = re.match(r'^(.*?)[（(]([^）)]+)[）)]$', name)
    if m:
        base = m.group(1).strip()
        note = m.group(2).strip()
        # 如果 base 是"不吃/外出/不用"这类，视为纯特殊要求
        if base in ("不吃", "不用", "外出", "无", "停"):
            return ("", f"{base}({note})")
        return (base, note)
    # 无括号：如果本身就是特殊标记
    if name in ("不吃", "外出", "不用", "停"):
        return ("", name)
    return (name, "")


def _ocr_extract(image_b64: str) -> str:
    """调用 Baidu Unlimited-OCR 提取单张图片文字。失败返回空字符串。"""
    try:
        import httpx
        ocr_url = os.environ.get("DL_OCR_URL", "http://192.168.10.247:18080")
        ocr_token = os.environ.get("DL_OCR_API_TOKEN", "")
        headers = {"Authorization": f"Bearer {ocr_token}"} if ocr_token else {}
        r = httpx.post(f"{ocr_url}/v1/ocr", json={"image": image_b64},
                       headers=headers, timeout=120)
        if r.status_code == 200:
            return r.json().get("text", "").strip()
    except Exception:
        pass
    return ""


def _ocr_extract_multi(images: List[str]) -> str:
    """提取多张图片文字，按页码标注拼接（用于跨页菜单）。

    返回 "【第1页】...\n【第2页】..."；单张时等价于 _ocr_extract。
    """
    if not images:
        return ""
    if len(images) == 1:
        return _ocr_extract(images[0])

    parts = []
    for i, img in enumerate(images, start=1):
        text = _ocr_extract(img)
        if text:
            parts.append(f"【第{i}页】\n{text}")
    return "\n\n".join(parts)


def _llm_structure_menu(ocr_text: str, dish_names: List[str]) -> dict:
    """周菜单：LLM 结构化 + 纠错（不识别特殊要求）。"""
    return _llm_structure(ocr_text, dish_names, mode="menu")


def _llm_structure(ocr_text: str, dish_names: List[str], mode: str = "menu") -> dict:
    """用 LLM 把 OCR 原始文字结构化，识别星期/餐次并纠错对齐菜品库。

    mode='menu'：周菜单（每餐菜名列表）
    mode='order'：老人点餐（菜名可带括号特殊要求，如'清蒸鲈鱼(少盐)'，或'不吃'）

    返回 {周一: {早餐: [菜名...], ...}, ...}；LLM 失败时返回 {}。
    """
    days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    meals = ["早餐", "午餐", "晚餐"]

    if mode == "order":
        special_rule = (
            "- 如果某道菜有特殊要求（少盐、少油、忌口、糖尿病餐等），在菜名后加括号标注，"
            "如'清蒸鲈鱼(少盐)'\n"
            "- 如果某餐不吃或外出，输出一个元素\"不吃\"，可加括号原因，如\"不吃(外出)\"\n"
        )
    else:
        special_rule = ""

    system_prompt = (
        "你是养老院菜单数据整理助手。用户会给你一段 OCR 识别的菜单文字（可能包含错别字），"
        "以及一份标准菜品清单。你的任务：\n"
        "1. 识别菜单中的星期（周一~周日）和餐次（早餐/午餐/晚餐）结构\n"
        "2. 把识别出的菜名纠正为标准菜品清单里的名字（OCR 错别字对齐，如'清蒸鲈渔'→'清蒸鲈鱼'）\n"
        "3. 只输出 JSON，不要任何解释、不要 markdown 代码块标记\n\n"
        "输出格式（严格 JSON）：\n"
        '{"周一": {"早餐": ["菜名1", "菜名2"], "午餐": [...], "晚餐": [...]}, "周二": {...}}\n\n'
        "规则：\n"
        "- 菜名尽量用标准清单里的标准名，错别字要纠正\n"
        "- 如果某菜名在清单里没有对应，保留原样\n"
        "- 只输出识别到的星期和餐次，没有的不要输出\n"
        "- 菜名用顿号或逗号分隔的，拆成多个元素\n"
        + special_rule
    )

    user_prompt = (
        f"OCR 识别文字：\n{ocr_text[:6000]}\n\n"
        f"标准菜品清单（{len(dish_names)} 道）：\n" + "、".join(dish_names)
    )

    reply = llm_chat(system_prompt, user_prompt, temperature=0.1, max_tokens=2000)
    if not reply:
        return {}

    # 解析 LLM 输出，容忍 markdown 代码块和多余字符
    try:
        cleaned = reply.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        data = json.loads(cleaned)
    except Exception:
        # 尝试提取第一个 {...} 块
        m = re.search(r'\{.*\}', reply, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}

    # 只保留合法的星期和餐次，值转成字符串列表
    result = {}
    if isinstance(data, dict):
        for day, day_meals in data.items():
            if day not in days:
                continue
            result[day] = {}
            if isinstance(day_meals, dict):
                for meal, names in day_meals.items():
                    if meal not in meals:
                        continue
                    if isinstance(names, list):
                        result[day][meal] = [str(n) for n in names]
                    elif isinstance(names, str):
                        result[day][meal] = [names]
    return result


def _find_best_dish(name: str, dishes_by_name: dict) -> tuple:
    """容错匹配：菜名整词匹配失败时，用最长公共子串找最接近的菜品。"""
    best_id, best_name, best_score = None, None, 0.0
    for dname, did in dishes_by_name.items():
        score = _dish_match(name, dname)
        if score > best_score:
            best_score = score
            best_id, best_name = did, dname
    if best_score >= 0.7:
        return best_id, best_name
    return None, None


def _dish_match(line: str, dish_name: str) -> float:
    """Whole-word substring matching for dish names.

    Returns 1.0 if the dish name appears verbatim in the OCR line,
    a lower score if a long contiguous substring matches (handles OCR
    dropping a trailing character), and 0.0 otherwise. This rejects the
    single-character-overlap false positives that plagued fuzzy matching.
    """
    line = line.replace(" ", "").replace("　", "")
    dish = dish_name.replace(" ", "")
    if not dish or not line:
        return 0.0
    # Exact whole-word containment — highest confidence.
    if dish in line:
        return 1.0
    # Longest common contiguous substring fallback (OCR may miss 1 trailing char).
    lcs = _longest_common_substring(line, dish)
    ratio = lcs / len(dish)
    # Require most of the dish name to match contiguously.
    return ratio if ratio >= 0.7 else 0.0


def _longest_common_substring(a: str, b: str) -> int:
    """Length of the longest common contiguous substring of a and b."""
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    longest = 0
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                longest = max(longest, dp[i][j])
    return longest
