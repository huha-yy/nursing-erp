import pytest


@pytest.mark.django_db
def test_low_stock_detection():
    from operations.models import InventoryItem

    item = InventoryItem.objects.create(
        name="尿不湿 L码", category="护理耗材", quantity=5, unit="包", safety_stock=10
    )
    assert item.is_low_stock is True

    item.quantity = 20
    item.save()
    assert item.is_low_stock is False


@pytest.mark.django_db
def test_stock_in_updates_quantity():
    from operations.models import InventoryItem, StockIn

    item = InventoryItem.objects.create(
        name="口罩", category="防护用品", quantity=100, unit="只", safety_stock=20
    )
    StockIn.objects.create(item=item, quantity=50, date="2026-08-04")
    item.refresh_from_db()
    assert item.quantity == 150


@pytest.mark.django_db
def test_stock_out_decreases_quantity():
    from operations.models import InventoryItem, StockOut

    item = InventoryItem.objects.create(
        name="消毒液", category="清洁消毒", quantity=35, unit="瓶", safety_stock=10
    )
    StockOut.objects.create(item=item, quantity=5, taken_by="张护士", date="2026-08-04")
    item.refresh_from_db()
    assert item.quantity == 30


@pytest.mark.django_db
def test_maintenance_order():
    from operations.models import MaintenanceOrder

    order = MaintenanceOrder.objects.create(
        equipment_name="空调", location="5号楼2层",
        fault_description="制冷不足", reported_by="赵护士"
    )
    assert order.status == "pending"
    assert str(order).startswith("空调")


@pytest.mark.django_db
def test_approval_workflow():
    from operations.models import Approval

    approval = Approval.objects.create(
        applicant_name="张护士", approval_type="leave",
        title="请假申请", content="8月10日请假一天"
    )
    assert approval.status == "pending"

    approval.status = "approved"
    approval.save()
    assert approval.status == "approved"
