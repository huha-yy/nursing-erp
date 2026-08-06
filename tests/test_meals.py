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
