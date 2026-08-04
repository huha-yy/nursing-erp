import pytest


@pytest.mark.django_db
def test_create_meal_order():
    from residents.models import Resident
    from meals.models import MealPlan, MealOrder

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    order = MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
        menu_choice="清蒸鲈鱼、炒青菜、米饭",
        special_requests="少盐",
    )
    assert order.status == "ordered"
    assert order.special_requests == "少盐"


@pytest.mark.django_db
def test_meal_order_cancellation():
    from residents.models import Resident
    from meals.models import MealOrder, MealModificationLog

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    order = MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
        menu_choice="清蒸鲈鱼、米饭",
    )
    order.cancel("老人外出")
    order.refresh_from_db()
    assert order.status == "cancelled"

    log = MealModificationLog.objects.first()
    assert log.action == "cancel"
    assert log.reason == "老人外出"


@pytest.mark.django_db
def test_meal_finance_calculation():
    from residents.models import Resident
    from meals.models import MealOrder, MealFinance

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    # 2 orders + 1 cancelled
    MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="早餐",
        menu_choice="小米粥、鸡蛋"
    )
    MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
        menu_choice="清蒸鲈鱼、米饭"
    )
    MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="晚餐",
        menu_choice="肉末蒸蛋、馒头", status="cancelled"
    )

    finance = MealFinance.generate_monthly(resident, "2026-08", price_per_meal=15)
    assert finance.total_meals == 3
    assert finance.cancelled == 1
    assert finance.amount == 30  # 2 × 15


@pytest.mark.django_db
def test_meal_order_modify():
    from residents.models import Resident
    from meals.models import MealOrder, MealModificationLog

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    order = MealOrder.objects.create(
        resident=resident, date="2026-08-04", meal_type="午餐",
        menu_choice="清蒸鲈鱼、米饭",
    )
    order.modify_menu("红烧排骨、米饭", "老人要求换菜")
    order.refresh_from_db()
    assert order.status == "modified"
    assert "红烧排骨" in order.menu_choice

    log = MealModificationLog.objects.first()
    assert log.action == "modify"
