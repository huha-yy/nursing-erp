import pytest


@pytest.mark.django_db
def test_create_meal_order():
    from residents.models import Resident
    from meals.models import Dish, MealOrder

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    d1 = Dish.objects.create(name="清蒸鲈鱼", category="荤菜")
    d2 = Dish.objects.create(name="炒青菜", category="素菜")
    d3 = Dish.objects.create(name="米饭", category="主食")

    order = MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
        special_requests="少盐",
    )
    order.dishes.add(d1, d2, d3)
    assert order.status == "ordered"
    assert order.special_requests == "少盐"
    assert order.dishes.count() == 3


@pytest.mark.django_db
def test_meal_order_cancellation():
    from residents.models import Resident
    from meals.models import Dish, MealOrder, MealModificationLog

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    d1 = Dish.objects.create(name="清蒸鲈鱼", category="荤菜")
    d2 = Dish.objects.create(name="米饭", category="主食")

    order = MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
    )
    order.dishes.add(d1, d2)
    order.cancel("老人外出")
    order.refresh_from_db()
    assert order.status == "cancelled"

    log = MealModificationLog.objects.first()
    assert log.action == "cancel"
    assert log.reason == "老人外出"


@pytest.mark.django_db
def test_meal_finance_calculation():
    from residents.models import Resident
    from meals.models import Dish, MealOrder, MealFinance

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    d = Dish.objects.create(name="小米粥", category="粥类")

    MealOrder.objects.create(resident=resident, date="2026-08-04", meal_type="早餐").dishes.add(d)
    MealOrder.objects.create(resident=resident, date="2026-08-04", meal_type="午餐").dishes.add(d)
    MealOrder.objects.create(resident=resident, date="2026-08-04", meal_type="晚餐", status="cancelled").dishes.add(d)

    finance = MealFinance.generate_monthly(resident, "2026-08", price_per_meal=15)
    assert finance.total_meals == 3
    assert finance.cancelled == 1
    assert finance.amount == 30


@pytest.mark.django_db
def test_meal_order_modify():
    from residents.models import Resident
    from meals.models import Dish, MealOrder, MealModificationLog

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    d1 = Dish.objects.create(name="清蒸鲈鱼", category="荤菜")
    d2 = Dish.objects.create(name="红烧排骨", category="荤菜")
    d3 = Dish.objects.create(name="米饭", category="主食")

    order = MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
    )
    order.dishes.add(d1, d3)

    order.modify_dishes([d2.id, d3.id], "老人要求换菜")
    order.refresh_from_db()
    assert order.status == "modified"
    assert order.dishes.count() == 2
    assert d2 in order.dishes.all()

    log = MealModificationLog.objects.first()
    assert log.action == "modify"


# ---- 防重守卫（2026-08-24）----
# 业务规则：同一老人同一日期同一餐次只允许一张有效订单（已退餐可重点）。
# 背景：OCR 重复识别曾给张国栋造出 171 条同周重复点餐，直接抬高月结餐费。


@pytest.mark.django_db
def test_meal_order_unique_active_constraint():
    """模型层条件唯一约束：有效订单撞同槽位 IntegrityError，退餐的不算"""
    from django.db import IntegrityError, transaction

    from meals.models import MealOrder
    from residents.models import Resident

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    MealOrder.objects.create(resident=resident, date="2026-08-18", meal_type="午餐")
    with pytest.raises(IntegrityError), transaction.atomic():
        MealOrder.objects.create(resident=resident, date="2026-08-18", meal_type="午餐")

    # 已退餐的槽位可以重新点
    MealOrder.objects.create(
        resident=resident, date="2026-08-19", meal_type="晚餐", status="cancelled"
    )
    reorder = MealOrder.objects.create(resident=resident, date="2026-08-19", meal_type="晚餐")
    assert reorder.status == "ordered"

    # 同日不同餐次互不影响
    MealOrder.objects.create(resident=resident, date="2026-08-18", meal_type="早餐")


@pytest.mark.django_db
def test_create_meal_order_api_rejects_duplicate(client):
    """单条创建：库中已有有效订单 → 400；退餐后可重点"""
    from meals.models import MealOrder
    from residents.models import Resident

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    body = {
        "resident_id": resident.id, "date": "2026-08-18", "meal_type": "午餐",
        "dish_ids": [], "special_requests": "", "ordered_by": "",
    }
    first = client.post("/api/meal-orders/", body, content_type="application/json")
    assert first.status_code == 200

    dup = client.post("/api/meal-orders/", body, content_type="application/json")
    assert dup.status_code == 400
    assert "已有一张有效订单" in dup.json()["detail"]
    assert MealOrder.objects.count() == 1

    order = MealOrder.objects.get()
    client.post(f"/api/meal-orders/{order.id}/cancel/?reason=不吃")
    ok = client.post("/api/meal-orders/", body, content_type="application/json")
    assert ok.status_code == 200
    assert MealOrder.objects.count() == 2
    assert MealOrder.objects.exclude(status="cancelled").count() == 1


@pytest.mark.django_db
def test_batch_create_rejects_duplicate_wholesale(client):
    """批量创建：批内重复 / 撞库中已有订单 → 整批 400，一条都不建"""
    from meals.models import MealOrder
    from residents.models import Resident

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    meal = {"resident_id": resident.id, "date": "2026-08-18", "meal_type": "午餐",
            "dish_ids": [], "special_requests": "", "ordered_by": ""}
    dinner = {**meal, "meal_type": "晚餐"}

    # 批内重复
    resp = client.post(
        "/api/meal-orders/batch/", [meal, dinner, meal],
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "整批拒绝" in resp.json()["detail"]
    assert MealOrder.objects.count() == 0

    # 撞库中已有有效订单（张国栋 18 号午餐已建）
    client.post("/api/meal-orders/", meal, content_type="application/json")
    resp = client.post(
        "/api/meal-orders/batch/", [dinner, meal],
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "已有一张有效订单" in resp.json()["detail"]
    assert MealOrder.objects.count() == 1  # 半批数据也不留


@pytest.mark.django_db
def test_ocr_batch_create_rejects_duplicate(client):
    """OCR 批量：重拍同一周 → 撞库中已有订单整批 400，一条都不建"""
    from meals.models import Dish, MealOrder
    from residents.models import Resident

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    d = Dish.objects.create(name="清蒸鲈鱼", category="荤菜")
    # 8-17 周一午餐已有有效订单
    MealOrder.objects.create(
        resident=resident, date="2026-08-17", meal_type="午餐"
    ).dishes.add(d)

    payload = [
        {"resident_id": resident.id, "day": "周一", "meal_type": "午餐",
         "week_start": "2026-08-17", "dish_ids": [d.id]},
        {"resident_id": resident.id, "day": "周一", "meal_type": "晚餐",
         "week_start": "2026-08-17", "dish_ids": [d.id]},
    ]
    resp = client.post(
        "/api/meal-order-ocr/batch-create/", payload, content_type="application/json"
    )
    assert resp.status_code == 400
    assert "已有一张有效订单" in resp.json()["detail"]
    # 整批拒绝：周一晚餐也没建
    assert MealOrder.objects.count() == 1
    assert not MealOrder.objects.filter(date="2026-08-17", meal_type="晚餐").exists()
