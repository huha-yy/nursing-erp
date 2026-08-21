"""staff FK 改造测试 — Q2 定稿（阶段一第二批）。

分层：
1. StaffFkMixin save() 三分支：FK→字符串同步 / 字符串→唯一匹配自动挂 /
   歧义·无匹配保持 null；update_fields 兼容
2. StockIn/StockOut：mixin 与库存增减覆写共存（MRO 不互相干扰）
3. 回填命令：挂接、幂等、dry-run、歧义清单、update() 不触发库存副作用

红线：字符串列原样保留，AI 侧 /api/ 契约零变动。
"""

import itertools
from io import StringIO

import pytest

_ids = itertools.count(1)


def _emp(name, dept="护理科", building=""):
    from django.contrib.auth.models import User

    from staff.models import Employee

    user = User.objects.create_user(username=f"emp{_ids.__next__()}", password="x")
    return Employee.objects.create(
        user=user, name=name, dept=dept, building=building, phone="13800000000"
    )


def _resident(**kw):
    from residents.models import Resident

    kw.setdefault("name", "测试老人")
    kw.setdefault("building", "1号楼")
    kw.setdefault("floor", "1层")
    kw.setdefault("room", "101")
    kw.setdefault("care_level", "自理")
    kw.setdefault("id_card", f"33010019480101000{_ids.__next__():03d}")
    return Resident(**kw)


def _log(**kw):
    from residents.models import NursingLog

    if "resident" not in kw:
        resident = _resident()
        resident.save()
        kw["resident"] = resident
    kw.setdefault("log_date", "2026-08-20")
    kw.setdefault("category", "feeding")
    return NursingLog(**kw)


# ---- 1. StaffFkMixin 三分支 ----


@pytest.mark.django_db
def test_fk_set_syncs_string():
    """FK 已设 → 字符串同步为员工姓名（FK 为准）"""
    emp = _emp("李芳")
    log = _log(staff_name="写错的名字", staff_emp=emp)
    log.save()
    log.refresh_from_db()
    assert log.staff_name == "李芳"


@pytest.mark.django_db
def test_string_unique_match_autolinks():
    """字符串非空且姓名恰好唯一 → 自动挂 FK（API 写路径零改动的原因）"""
    _emp("冯德才")
    log = _log(staff_name="冯德才")
    log.save()
    log.refresh_from_db()
    assert log.staff_emp.name == "冯德才"
    assert log.staff_name == "冯德才"


@pytest.mark.django_db
def test_string_ambiguous_keeps_null():
    """重名歧义 → 不自动挂，保持 null 待人工处理"""
    _emp("刘主任")
    _emp("刘主任")
    log = _log(staff_name="刘主任")
    log.save()
    log.refresh_from_db()
    assert log.staff_emp is None
    assert log.staff_name == "刘主任"  # 字符串不动


@pytest.mark.django_db
def test_string_unmatched_keeps_null():
    """无匹配（错字/离职）→ 保持 null"""
    log = _log(staff_name="不存在的员工")
    log.save()
    log.refresh_from_db()
    assert log.staff_emp is None


@pytest.mark.django_db
def test_both_empty_skips():
    """两者皆空 → 正常保存不受影响"""
    log = _log(staff_name="")
    log.save()
    log.refresh_from_db()
    assert log.staff_emp is None
    assert log.staff_name == ""


@pytest.mark.django_db
def test_update_fields_gets_sync_columns_appended():
    """调用方传 update_fields 时，被同步的列自动追加，缓存不写一半"""
    a, b = _emp("张护士"), _emp("李护士")
    log = _log(staff_name="张护士")
    log.save()
    assert log.staff_emp == a

    # 换人：只声明 update_fields=["staff_emp"]，字符串列应被追加同步
    log.staff_emp = b
    log.save(update_fields=["staff_emp"])
    log.refresh_from_db()
    assert log.staff_name == "李护士"

    # 字符串→FK 方向：先模拟存量行（FK 置空），改字符串后自动挂接，
    # update_fields 应追加 FK 列
    type(log).objects.filter(pk=log.pk).update(staff_emp=None)  # 绕过 save()
    log.refresh_from_db()
    log.staff_name = "张护士"
    log.save(update_fields=["staff_name"])
    log.refresh_from_db()
    assert log.staff_emp == a
    assert log.staff_name == "张护士"


# ---- 2. StockIn/StockOut 共存（mixin + 自有 save() 覆写）----


@pytest.mark.django_db
def test_stockin_mixin_coexists_with_inventory():
    """入库：库存照常增加，操作人 FK 照常自动挂接"""
    from operations.models import InventoryItem, StockIn

    item = InventoryItem.objects.create(
        name="尿不湿", category="护理耗材", quantity=5, unit="包", safety_stock=10
    )
    _emp("陈总务", dept="总务科")
    record = StockIn.objects.create(
        item=item, quantity=3, supplier="测试供应商", date="2026-08-20", operator="陈总务"
    )

    item.refresh_from_db()
    assert item.quantity == 8  # 自有 save() 覆写生效
    record.refresh_from_db()
    assert record.operator_emp.name == "陈总务"  # mixin 生效


@pytest.mark.django_db
def test_stockout_mixin_coexists_with_inventory():
    from operations.models import InventoryItem, StockOut

    item = InventoryItem.objects.create(
        name="手套", category="防护用品", quantity=10, unit="盒", safety_stock=5
    )
    _emp("张护士")
    record = StockOut.objects.create(item=item, quantity=4, taken_by="张护士", date="2026-08-20")

    item.refresh_from_db()
    assert item.quantity == 6
    record.refresh_from_db()
    assert record.taken_by_emp.name == "张护士"


# ---- 3. 多模型冒烟（Task / MealOrder）----


@pytest.mark.django_db
def test_task_and_meal_order_autolink():
    from meals.models import MealOrder
    from staff.models import Task

    assigner, orderer = _emp("吴主任"), _emp("张护士")
    assignee = _emp("王护理")
    resident = _resident()
    resident.save()
    task = Task.objects.create(
        assigner_name="吴主任", assignee=assignee, title="巡楼", content=""
    )
    order = MealOrder.objects.create(
        resident=resident, date="2026-08-20", meal_type="午餐", ordered_by="张护士"
    )

    task.refresh_from_db()
    order.refresh_from_db()
    assert task.assigner_emp == assigner
    assert order.ordered_by_emp == orderer


# ---- 4. 回填命令 ----


def _run_backfill(dry_run=False):
    from django.core.management import call_command

    buf = StringIO()
    call_command("backfill_staff_fk", *(["--dry-run"] if dry_run else []), stdout=buf)
    return buf.getvalue()


def _seed_legacy_rows():
    """模拟存量行：FK 空 + 字符串非空。

    用 bulk_create 绕过 save()（不触发库存增减），还原历史数据的真实状态。
    """
    from django.contrib.auth.models import User

    from operations.models import InventoryItem, StockIn, StockOut
    from residents.models import NursingLog
    from staff.models import Employee

    def emp(name):
        user = User.objects.create_user(username=f"seed{_ids.__next__()}", password="x")
        return Employee.objects.create(user=user, name=name, dept="护理科", phone="1")

    _emp("唯一护理员")
    emp("重名人")
    emp("重名人")

    resident = _resident()
    resident.save()
    NursingLog.objects.bulk_create([
        NursingLog(resident=resident, log_date="2026-08-20", category="feeding",
                   staff_name="唯一护理员"),
        NursingLog(resident=resident, log_date="2026-08-20", category="hygiene",
                   staff_name="重名人"),
        NursingLog(resident=resident, log_date="2026-08-20", category="toilet",
                   staff_name="查无此人"),
    ])

    item = InventoryItem.objects.create(
        name="测试物品", category="护理耗材", quantity=100, unit="个", safety_stock=10
    )
    StockIn.objects.bulk_create([
        StockIn(item=item, quantity=1, date="2026-08-20", operator="唯一护理员"),
    ])
    StockOut.objects.bulk_create([
        StockOut(item=item, quantity=1, date="2026-08-20", taken_by="唯一护理员"),
    ])
    return item


@pytest.mark.django_db
def test_backfill_links_and_reports_lists():
    from residents.models import NursingLog

    item = _seed_legacy_rows()
    out = _run_backfill()

    # 挂接 3 条 = 日志×1（唯一护理员）+ 入库×1 + 领用×1
    assert "挂接 3 条" in out
    linked = NursingLog.objects.filter(staff_name="唯一护理员", staff_emp__isnull=False).count()
    assert linked == 1
    assert "[重名] 重名人" in out
    assert "[无匹配] 查无此人" in out
    assert item.quantity == 100  # bulk_create 未触发库存，回填也不该触发


@pytest.mark.django_db
def test_backfill_idempotent():
    from residents.models import NursingLog

    _seed_legacy_rows()
    _run_backfill()
    out2 = _run_backfill()
    assert "挂接 0 条" in out2
    # 歧义/无匹配行仍在锚点内（FK 空 + 字符串非空），每次都会列入清单
    assert NursingLog.objects.filter(staff_name="重名人", staff_emp__isnull=True).count() == 1


@pytest.mark.django_db
def test_backfill_dry_run_writes_nothing():
    from residents.models import NursingLog

    _seed_legacy_rows()
    out = _run_backfill(dry_run=True)
    assert "[计划]" in out
    assert NursingLog.objects.filter(staff_emp__isnull=False).count() == 0


@pytest.mark.django_db
def test_backfill_uses_update_not_save():
    """回归钉：回填绝不能走 save()——否则 StockIn 库存被二次增加。"""
    from operations.models import InventoryItem, StockIn

    # 正常创建（库存 5→8），再模拟"存量行"：改字符串并清 FK
    item = InventoryItem.objects.create(
        name="尿垫", category="护理耗材", quantity=5, unit="包", safety_stock=10
    )
    _emp("赵总务", dept="总务科")
    StockIn.objects.create(item=item, quantity=3, date="2026-08-20", operator="先随便")
    StockIn.objects.update(operator="赵总务", operator_emp=None)
    item.refresh_from_db()
    assert item.quantity == 8

    _run_backfill()
    item.refresh_from_db()
    assert item.quantity == 8  # 若回填误用 save()，这里会变成 11
    assert StockIn.objects.first().operator_emp.name == "赵总务"
