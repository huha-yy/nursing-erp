"""床位台账（四级模型）测试 — 2026-08-21 阶段一。

分层：
1. 模型层：链创建/唯一约束/字符串同步/一人一床/离院释放
2. 回填命令：链接、幂等、dry-run（见下文 Backfill 段）
3. API：/api/beds/、/api/beds/occupancy/、/api/residents/ 契约回归钉
4. 看板页：/beds/

核心不变式：未挂床位的老人行为与改造前完全一致（39 个存量测试全绿的保证）。
"""

import itertools
from io import StringIO

import pytest

_ids = itertools.count(1)


def _resident(**kw):
    """造一位老人，id_card 自动去重"""
    from residents.models import Resident

    kw.setdefault("name", "测试老人")
    kw.setdefault("building", "1号楼")
    kw.setdefault("floor", "1层")
    kw.setdefault("room", "101")
    kw.setdefault("care_level", "自理")
    kw.setdefault("id_card", f"33010019480101000{_ids.__next__():03d}")
    return Resident(**kw)


def _bed(building="1号楼", floor="1层", room="101", number="1", status=None):
    """造一张床（get_or_create 逐级建链）"""
    from beds.models import Bed, Building, Floor, Room

    b, _ = Building.objects.get_or_create(name=building)
    f, _ = Floor.objects.get_or_create(building=b, name=floor)
    r, _ = Room.objects.get_or_create(floor=f, number=room)
    defaults = {"status": status} if status else {}
    bed, _ = Bed.objects.get_or_create(room=r, number=number, defaults=defaults)
    return bed


# ---- 1. 模型层 ----


@pytest.mark.django_db
def test_bed_chain_creation_and_str():
    from beds.models import Bed, Building, Floor, Room

    building = Building.objects.create(name="1号楼")
    floor = Floor.objects.create(building=building, name="1层")
    room = Room.objects.create(floor=floor, number="101")
    bed = Bed.objects.create(room=room, number="1")

    assert str(building) == "1号楼"
    assert str(floor) == "1号楼 1层"
    assert str(room) == "1号楼 1层 101室"
    assert str(bed) == "1号楼 1层 101室-1床"
    assert bed.full_location == "1号楼 1层 101室 1床"
    assert bed.status == Bed.Status.AVAILABLE


@pytest.mark.django_db
def test_uniqueness_constraints():
    """同楼栋楼层重名/同楼层房间重号/同房间床位重号 → IntegrityError"""
    from django.db import IntegrityError, transaction

    from beds.models import Bed, Building, Floor, Room

    building = Building.objects.create(name="1号楼")
    with pytest.raises(IntegrityError), transaction.atomic():
        Building.objects.create(name="1号楼")  # 楼栋重名
    floor = Floor.objects.create(building=building, name="1层")

    with pytest.raises(IntegrityError), transaction.atomic():
        Floor.objects.create(building=building, name="1层")

    room = Room.objects.create(floor=floor, number="101")
    with pytest.raises(IntegrityError), transaction.atomic():
        Room.objects.create(floor=floor, number="101")

    Bed.objects.create(room=room, number="1")
    with pytest.raises(IntegrityError), transaction.atomic():
        Bed.objects.create(room=room, number="1")


@pytest.mark.django_db
def test_resident_bed_save_syncs_strings():
    """挂床位后 building/floor/room 字符串自动对齐床位链（即使初值不同）"""
    resident = _resident(building="写错的楼", floor="9层", room="999")
    resident.bed = _bed("1号楼", "1层", "101", "1")
    resident.save()

    resident.refresh_from_db()
    assert (resident.building, resident.floor, resident.room) == ("1号楼", "1层", "101")


@pytest.mark.django_db
def test_resident_without_bed_keeps_strings():
    """不挂床位的老人字符串原样保留（存量行为不变式）"""
    resident = _resident(building="3号楼", floor="2层", room="206")
    resident.save()

    resident.refresh_from_db()
    assert resident.bed_id is None
    assert (resident.building, resident.floor, resident.room) == ("3号楼", "2层", "206")


@pytest.mark.django_db
def test_bed_reassignment_resyncs_strings():
    """换床到另一栋楼，字符串跟随新床位链"""
    resident = _resident()
    resident.bed = _bed("1号楼", "1层", "101", "1")
    resident.save()
    resident.bed = _bed("5号楼", "2层", "203", "1")
    resident.save()

    resident.refresh_from_db()
    assert (resident.building, resident.floor, resident.room) == ("5号楼", "2层", "203")


@pytest.mark.django_db
def test_two_residents_same_bed_rejected():
    """一人一床：表单校验出中文报错，裸 create 触发 IntegrityError"""
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction

    bed = _bed("1号楼", "1层", "101", "1")
    first = _resident(name="甲")
    first.bed = bed
    first.save()

    second = _resident(name="乙")
    second.bed = bed
    with pytest.raises(ValidationError) as err:
        second.full_clean()
    assert "该床位已有老人入住" in str(err.value)

    second.building, second.floor, second.room = "1号楼", "1层", "101"
    with pytest.raises(IntegrityError), transaction.atomic():
        second.save()


@pytest.mark.django_db
def test_discharge_frees_bed_on_create_only():
    """新建离院记录释放床位且字符串保留；编辑离院记录不再误释放"""
    from residents.models import DischargeRecord

    resident = _resident()
    resident.bed = _bed("2号楼", "1层", "102", "1")
    resident.save()

    discharge = DischargeRecord.objects.create(
        resident=resident, discharge_type="出院", discharge_date="2026-08-20", reason="康复"
    )
    resident.refresh_from_db()
    assert resident.bed_id is None
    assert (resident.building, resident.floor, resident.room) == ("2号楼", "1层", "102")

    # 离院后床位重新安排给下一位老人，再编辑离院记录不得清空新入住
    new_resident = _resident(name="新入住")
    new_resident.bed = _bed("2号楼", "1层", "102", "1")
    new_resident.save()
    discharge.reason = "补录原因"
    discharge.save()

    new_resident.refresh_from_db()
    assert new_resident.bed_id is not None


@pytest.mark.django_db
def test_update_fields_save_still_syncs():
    """调用方传 update_fields 时同步列被追加，缓存不会写一半"""
    resident = _resident(building="旧楼", floor="旧层", room="旧房")
    resident.save()
    resident.bed = _bed("4号楼", "2层", "205", "1")
    resident.save(update_fields=["bed", "care_level"])

    resident.refresh_from_db()
    assert (resident.building, resident.floor, resident.room) == ("4号楼", "2层", "205")


# ---- 2. 回填命令 ----


def _run_backfill(dry_run=False):
    from django.core.management import call_command

    buf = StringIO()
    call_command("backfill_beds", *(["--dry-run"] if dry_run else []), stdout=buf)
    return buf.getvalue()


@pytest.mark.django_db
def test_backfill_links_and_idempotent():
    from beds.models import Bed, Building, Floor, Room
    from residents.models import Resident

    _resident(name="甲", building="1号楼", floor="1层", room="101").save()
    _resident(name="乙", building="1号楼", floor="2层", room="201").save()
    _resident(name="丙", building="3号楼", floor="1层", room="105").save()

    out = _run_backfill()
    assert Building.objects.count() == 2
    assert Floor.objects.count() == 3
    assert Room.objects.count() == 3
    assert Bed.objects.count() == 3
    assert Resident.objects.filter(bed__isnull=False).count() == 3
    assert "链接老人 3 位" in out

    # 幂等：二次运行零创建零链接
    out2 = _run_backfill()
    assert Building.objects.count() == 2
    assert Bed.objects.count() == 3
    assert "新建 楼栋0/楼层0/房间0/床位0" in out2
    assert "链接老人 0 位" in out2


@pytest.mark.django_db
def test_backfill_dry_run_creates_nothing():
    from beds.models import Bed, Building
    from residents.models import Resident

    _resident(name="甲", building="1号楼", floor="1层", room="101").save()

    out = _run_backfill(dry_run=True)
    assert Building.objects.count() == 0
    assert Bed.objects.count() == 0
    assert Resident.objects.filter(bed__isnull=False).count() == 0
    assert "[dry-run] 待处理老人 1 位" in out


@pytest.mark.django_db
def test_backfill_skips_occupied_bed():
    """两人字符串指向同一房间：先到先得，后者跳过并告警（防御性守卫）"""
    from beds.models import Bed
    from residents.models import Resident

    _resident(name="甲", building="1号楼", floor="1层", room="101").save()
    _resident(name="乙", building="1号楼", floor="1层", room="101").save()

    out = _run_backfill()
    assert Bed.objects.count() == 1  # 只有一张床
    assert Resident.objects.filter(bed__isnull=False).count() == 1
    assert "跳过" in out and "已被" in out
    assert "剩余未链接 1 位" in out


# ---- 3. API ----


def _seed_occupancy_data():
    """两栋楼：1号楼 2 床（1 住 1 空），2号楼 3 床（2 住 1 维修）"""
    a1, a2 = _bed("1号楼", "1层", "101", "1"), _bed("1号楼", "1层", "102", "1")
    b1 = _bed("2号楼", "1层", "201", "1")
    b2 = _bed("2号楼", "1层", "202", "1")
    b3 = _bed("2号楼", "1层", "203", "1", status="维修")

    r1 = _resident(name="甲")
    r1.bed, r1.building, r1.floor, r1.room = a1, "1号楼", "1层", "101"
    r1.save()
    r2 = _resident(name="乙")
    r2.bed = b1
    r2.save()  # 字符串自动同步为 2号楼
    r3 = _resident(name="丙")
    r3.bed = b2
    r3.save()
    return a1, a2, b1, b2, b3


@pytest.mark.django_db
def test_occupancy_api_math(client):
    from beds.models import Building

    Building.objects.create(name="空楼")  # 0 床楼栋也要出现且 rate=0
    _seed_occupancy_data()

    data = client.get("/api/beds/occupancy/").json()
    by_name = {b["building"]: b for b in data["buildings"]}
    assert by_name["1号楼"] == {
        "building": "1号楼", "total": 2, "occupied": 1, "free": 1,
        "maintenance": 0, "disabled": 0, "rate": 0.5,
    }
    assert by_name["2号楼"] == {
        "building": "2号楼", "total": 3, "occupied": 2, "free": 0,
        "maintenance": 1, "disabled": 0, "rate": 0.67,
    }
    assert by_name["空楼"]["total"] == 0 and by_name["空楼"]["rate"] == 0
    assert data["total"] == {
        "total": 5, "occupied": 3, "free": 1,
        "maintenance": 1, "disabled": 0, "rate": 0.6,
    }

    single = client.get("/api/beds/occupancy/", {"building": "1号楼"}).json()
    assert [b["building"] for b in single["buildings"]] == ["1号楼"]


@pytest.mark.django_db
def test_beds_list_filters(client):
    a1, a2, b1, b2, b3 = _seed_occupancy_data()

    body = client.get("/api/beds/", {"building": "1号楼"}).json()
    assert set(body) >= {"items"}  # 分页包络
    assert len(body["items"]) == 2

    free = client.get("/api/beds/", {"building": "1号楼", "occupied": "false"}).json()["items"]
    assert [i["id"] for i in free] == [a2.id]
    assert free[0]["occupant"] is None

    ok = client.get("/api/beds/", {"status": "可用"}).json()["items"]
    assert {i["id"] for i in ok} == {a1.id, a2.id, b1.id, b2.id}  # 维修床不在列

    occ = client.get("/api/beds/", {"occupied": "true"}).json()["items"]
    assert {i["id"] for i in occ} == {a1.id, b1.id, b2.id}

    hit = client.get("/api/beds/", {"search": "203"}).json()["items"]
    assert [i["id"] for i in hit] == [b3.id]

    # 单条字段形状（AI 侧契约）
    item = client.get("/api/beds/", {"search": "101"}).json()["items"][0]
    assert item["building"] == "1号楼" and item["floor"] == "1层"
    assert item["room"] == "101" and item["bed"] == "1"
    assert item["full_location"] == "1号楼 1层 101室 1床"
    assert item["status"] == "可用"
    assert item["occupant"]["name"] == "甲" and item["occupant"]["care_level"] == "自理"


@pytest.mark.django_db
def test_residents_api_contract_regression(client):
    """契约钉：回填挂床后 /api/residents/ 的字符串字段与回填前完全一致"""
    _resident(name="甲", building="1号楼", floor="1层", room="101").save()
    _resident(name="乙", building="2号楼", floor="2层", room="202").save()
    before = {
        i["name"]: (i["building"], i["floor"], i["room"])
        for i in client.get("/api/residents/").json()["items"]
    }

    _run_backfill()

    after = {
        i["name"]: (i["building"], i["floor"], i["room"])
        for i in client.get("/api/residents/").json()["items"]
    }
    assert after == before
    assert after["甲"] == ("1号楼", "1层", "101")

    only1 = client.get("/api/residents/", {"building": "1号楼"}).json()["items"]
    assert [i["name"] for i in only1] == ["甲"]


# ---- 4. 看板页 ----


@pytest.mark.django_db
def test_bed_board_page(db, django_user_model):
    from django.test import Client

    _seed_occupancy_data()
    user = django_user_model.objects.create_user(username="viewer", password="pw123456")
    c = Client()
    c.force_login(user)

    resp = c.get("/beds/")
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "床位看板" in content and "1号楼" in content and "2号楼" in content


@pytest.mark.django_db
def test_bed_board_anonymous_redirects():
    from django.test import Client

    resp = Client().get("/beds/")
    assert resp.status_code == 302
    assert resp["Location"].startswith("/admin/login/")


# ---- 5. admin 楼栋隔离 ----


def _scoped_user(building: str):
    from django.contrib.auth.models import User

    from staff.models import Employee

    user = User.objects.create_user(username=f"cg_{building}", password="x", is_staff=True)
    Employee.objects.create(
        user=user, name=f"{building}护理员", dept="护理科", building=building, phone="13800000000"
    )
    return user


@pytest.mark.django_db
def test_bed_changelist_scoped_for_employee():
    """3号楼护理员在床位台账列表只能看到 3号楼的床"""
    from django.contrib.admin import site
    from django.test import RequestFactory

    from beds.admin import BedAdmin
    from beds.models import Bed

    _bed("1号楼", "1层", "101", "1")
    _bed("3号楼", "2层", "201", "1")
    _bed("3号楼", "2层", "202", "1")

    request = RequestFactory().get("/")
    request.user = _scoped_user("3号楼")
    qs = BedAdmin(Bed, site).get_queryset(request)
    assert qs.count() == 2
    assert all(b.room.floor.building.name == "3号楼" for b in qs)


@pytest.mark.django_db
def test_bed_dropdown_scoped_for_employee():
    """老人编辑表单里的床选择器只出本楼栋的床（跨楼栋写漏洞的回归钉）"""
    from django.contrib.admin import site
    from django.test import RequestFactory

    from residents.admin import ResidentAdmin
    from residents.models import Resident

    _bed("1号楼", "1层", "101", "1")
    _bed("3号楼", "2层", "201", "1")
    _bed("3号楼", "2层", "202", "1")

    request = RequestFactory().get("/")
    request.user = _scoped_user("3号楼")
    field = ResidentAdmin(Resident, site).formfield_for_foreignkey(
        Resident._meta.get_field("bed"), request
    )
    locs = sorted(b.full_location for b in field.queryset)
    assert locs == ["3号楼 2层 201室 1床", "3号楼 2层 202室 1床"]


def test_unfold_sidebar_lists_beds_group():
    """回归钉：unfold SIDEBAR 是点名制（show_all_applications=False），
    漏列的 app 整组不显示——床位组曾静默漏配（2026-08-24 用户发现）。"""
    from django.conf import settings

    nav = settings.UNFOLD["SIDEBAR"]["navigation"]
    group = next((g for g in nav if g["title"] == "床位管理"), None)
    assert group is not None, "侧边栏缺少「床位管理」组"
    links = [i["link"] for i in group["items"]]
    assert "/beds/" in links  # 床位看板
    for model in ("building", "floor", "room", "bed"):
        assert f"/admin/beds/{model}/" in links  # 四级台账
