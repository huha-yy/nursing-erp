"""/api/ 楼栋过滤测试（阶段一第二批，隐患 #3）。

覆盖：
1. key 路径：无头全量（契约钉——dl-control 未升级前一切照旧）；
   X-Building 过滤；未知名 400 fail-loud
2. session 路径：楼长仅本楼；管理层/superuser 全量；伪造 X-Building 头无效
3. 详情：越权与缺失统一 404（含修复"缺失 id 裸 get 500"回归钉）
4. 写路径：越权 403；batch 预检整批拒绝；cancel 越权 403
5. employees：本楼 + building="" 管理层；attendance 越权 404
6. beds：scope 覆盖 ?building= 参数（统计类端点语义）
"""

import itertools

import pytest
from django.contrib.auth.models import User
from django.test import Client

_ids = itertools.count(1)


def _resident(building, name=None):
    from residents.models import Resident

    return Resident.objects.create(
        name=name or f"{building}老人",
        building=building,
        floor="1层",
        room=f"1{_ids.__next__():02d}",
        care_level="自理",
        id_card=f"33010019480101000{_ids.__next__():03d}",
    )


def _user(building, superuser=False, username=None):
    """楼长（building=1号楼）/ 管理层（building=""）/ superuser"""
    from staff.models import Employee

    user = User.objects.create_user(
        username=username or f"u{_ids.__next__()}", password="x", is_superuser=superuser
    )
    Employee.objects.create(
        user=user, name=f"员工{_ids.__next__()}", dept="护理科", building=building, phone="1"
    )
    return user


def _login_client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def two_buildings(db):
    """1号楼/2号楼 各 1 位老人 + 台账楼栋记录（X-Building 校验用）。"""
    from beds.models import Building

    Building.objects.create(name="1号楼")
    Building.objects.create(name="2号楼")
    return _resident("1号楼"), _resident("2号楼")


# ---- 1. key 路径 ----


@pytest.mark.django_db
def test_key_without_header_sees_all(client, two_buildings):
    """契约钉：key 不带 X-Building → 全院（dl-control 升级前的现状）"""
    items = client.get("/api/residents/").json()["items"]
    assert {i["building"] for i in items} == {"1号楼", "2号楼"}


@pytest.mark.django_db
def test_key_with_building_header_scoped(client, two_buildings):
    r1, r2 = two_buildings
    items = client.get("/api/residents/", HTTP_X_BUILDING="1号楼").json()["items"]
    assert [i["id"] for i in items] == [r1.id]

    # 与显式 ?building= 叠加：一致时结果相同，冲突时空集（不报错）
    same = client.get("/api/residents/", {"building": "1号楼"}, HTTP_X_BUILDING="1号楼")
    assert [i["id"] for i in same.json()["items"]] == [r1.id]
    conflict = client.get("/api/residents/", {"building": "2号楼"}, HTTP_X_BUILDING="1号楼")
    assert conflict.json()["items"] == []


@pytest.mark.django_db
def test_key_percent_encoded_header_decoded(client, two_buildings):
    """线上契约钉：dl-control 对中文楼栋名 percent-encode（httpx 只收 ASCII 头值），
    ERP 侧 unquote 还原——编码头与裸中文必须等价。"""
    r1, _ = two_buildings
    for header in ("1%E5%8F%B7%E6%A5%BC", "1号楼"):
        items = client.get("/api/residents/", HTTP_X_BUILDING=header).json()["items"]
        assert [i["id"] for i in items] == [r1.id]


@pytest.mark.django_db
def test_key_unknown_building_400(client, two_buildings):
    """未知名 fail-loud 400：暴露 dl-control 侧名称与台账失配"""
    resp = client.get("/api/residents/", HTTP_X_BUILDING="7号楼")
    assert resp.status_code == 400
    assert "7号楼" in resp.json()["detail"]


# ---- 2. session 路径 ----


@pytest.mark.django_db
def test_session_building_head_scoped(two_buildings):
    r1, _ = two_buildings
    c = _login_client(_user("1号楼"))
    items = c.get("/api/residents/").json()["items"]
    assert [i["id"] for i in items] == [r1.id]


@pytest.mark.django_db
def test_session_management_and_superuser_see_all(two_buildings):
    for u in (_user(""), _user("", superuser=True, username="boss")):
        items = _login_client(u).get("/api/residents/").json()["items"]
        assert len(items) == 2


@pytest.mark.django_db
def test_session_ignores_forged_building_header(two_buildings):
    """session 路径忽略 X-Building 头——范围只来自员工档案，防伪造"""
    r1, _ = two_buildings
    c = _login_client(_user("1号楼"))
    items = c.get("/api/residents/", HTTP_X_BUILDING="2号楼").json()["items"]
    assert [i["id"] for i in items] == [r1.id]  # 伪造头无效


# ---- 3. 详情 404 ----


@pytest.mark.django_db
def test_detail_out_of_scope_and_missing_both_404(client, two_buildings):
    _, r2 = two_buildings
    assert client.get(f"/api/residents/{r2.id}/", HTTP_X_BUILDING="1号楼").status_code == 404
    missing = client.get("/api/residents/99999/")  # 回归钉：原先裸 get → 500
    assert missing.status_code == 404

    # 子资源同理
    assert client.get(f"/api/residents/{r2.id}/logs/", HTTP_X_BUILDING="1号楼").status_code == 404
    assert (
        client.get(f"/api/residents/{r2.id}/health/", HTTP_X_BUILDING="1号楼").status_code == 404
    )


# ---- 4. 写路径 ----


@pytest.mark.django_db
def test_write_out_of_scope_403(client, two_buildings):
    _, r2 = two_buildings
    resp = client.post(
        "/api/nursing-logs/",
        {"resident_id": r2.id, "category": "feeding", "detail": "x", "staff_name": "张护士"},
        content_type="application/json",
        HTTP_X_BUILDING="1号楼",
    )
    assert resp.status_code == 403

    missing = client.post(
        "/api/nursing-logs/",
        {"resident_id": 99999, "category": "feeding"},
        content_type="application/json",
        HTTP_X_BUILDING="1号楼",
    )
    assert missing.status_code == 404


@pytest.mark.django_db
def test_meal_order_batch_first_violation_rejects_whole_batch(client, two_buildings):
    """预检全部老人：任一条越权 → 整批 403，一条都不建"""
    r1, r2 = two_buildings
    payload = [
        {"resident_id": r1.id, "date": "2026-08-20", "meal_type": "午餐", "dish_ids": []},
        {"resident_id": r2.id, "date": "2026-08-20", "meal_type": "午餐", "dish_ids": []},
    ]
    resp = client.post(
        "/api/meal-orders/batch/", payload,
        content_type="application/json", HTTP_X_BUILDING="1号楼",
    )
    assert resp.status_code == 403
    assert "整批拒绝" in resp.json()["detail"]

    from meals.models import MealOrder

    assert MealOrder.objects.count() == 0  # 半批数据也不留

    # 全部本楼 → 正常创建（2026-08-24 起同老人同餐次唯一，改用两个不同餐次）
    ok = client.post(
        "/api/meal-orders/batch/",
        [
            {**payload[0], "meal_type": "午餐"},
            {**payload[0], "meal_type": "晚餐"},
        ],
        content_type="application/json", HTTP_X_BUILDING="1号楼",
    )
    assert ok.status_code == 200
    assert MealOrder.objects.count() == 2


@pytest.mark.django_db
def test_meal_order_cancel_scoped(client, two_buildings):
    from meals.models import MealOrder

    _, r2 = two_buildings
    order = MealOrder.objects.create(resident=r2, date="2026-08-20", meal_type="晚餐")

    resp = client.post(
        f"/api/meal-orders/{order.id}/cancel/?reason=x", HTTP_X_BUILDING="1号楼"
    )
    assert resp.status_code == 403
    assert client.post("/api/meal-orders/99999/cancel/").status_code == 404  # 原 500

    ok = client.post(f"/api/meal-orders/{order.id}/cancel/?reason=x")  # 全院可退
    assert ok.status_code == 200
    order.refresh_from_db()
    assert order.status == "cancelled"


# ---- 5. employees / attendance / schedules / incidents / meal-finance ----


@pytest.mark.django_db
def test_employees_includes_management_for_scoped(client, two_buildings):
    from staff.models import Employee

    mgmt = Employee.objects.create(
        user=User.objects.create_user(username="mgmt", password="x"),
        name="管理层", dept="综合办", building="", phone="1",
    )
    b1 = Employee.objects.create(
        user=User.objects.create_user(username="b1cg", password="x"),
        name="一号楼护理", dept="护理科", building="1号楼", phone="1",
    )
    b2 = Employee.objects.create(
        user=User.objects.create_user(username="b2cg", password="x"),
        name="二号楼护理", dept="护理科", building="2号楼", phone="1",
    )

    items = client.get("/api/employees/", HTTP_X_BUILDING="1号楼").json()["items"]
    assert {i["id"] for i in items} == {mgmt.id, b1.id}  # 本楼 + 管理层，不含别楼

    # attendance：别楼员工 404
    assert (
        client.get(f"/api/employees/{b2.id}/attendance/", HTTP_X_BUILDING="1号楼").status_code
        == 404
    )
    assert (
        client.get(f"/api/employees/{b1.id}/attendance/", HTTP_X_BUILDING="1号楼").status_code
        == 200
    )


@pytest.mark.django_db
def test_list_sweep_incidents_schedules_meal_finance(client, two_buildings):
    """incidents/schedules/meal-finance 列表按各自路径过滤"""
    from incidents.models import IncidentReport
    from meals.models import MealFinance
    from staff.models import Schedule

    r1, r2 = two_buildings
    emp = User.objects.create_user(username="swemp", password="x")
    from staff.models import Employee

    employee = Employee.objects.create(
        user=emp, name="排班员", dept="护理科", building="1号楼", phone="1"
    )
    IncidentReport.objects.create(resident=r1, category="fall", severity="info")
    IncidentReport.objects.create(resident=r2, category="fall", severity="info")
    Schedule.objects.create(employee=employee, date="2026-08-20", shift="白班", building="1号楼")
    Schedule.objects.create(employee=employee, date="2026-08-20", shift="夜班", building="2号楼")
    MealFinance.objects.create(resident=r1, month="2026-08", amount=10)
    MealFinance.objects.create(resident=r2, month="2026-08", amount=20)

    h = {"HTTP_X_BUILDING": "1号楼"}
    incidents = client.get("/api/incidents/", **h).json()["items"]
    assert {i["resident_name"] for i in incidents} == {r1.name}

    schedules = client.get("/api/schedules/", **h).json()["items"]
    assert {s["building"] for s in schedules} == {"1号楼"}

    finance = client.get("/api/meal-finance/", **h).json()["items"]
    assert {f["resident_name"] for f in finance} == {r1.name}


# ---- 6. beds：scope 覆盖语义 ----


@pytest.mark.django_db
def test_beds_scope_overrides_explicit_param(client, two_buildings):
    """统计/台账类端点：scope 覆盖 ?building=（叠加只会冲突空集）"""
    from beds.models import Bed, Building, Floor, Room

    for name in ("1号楼", "2号楼"):
        b = Building.objects.get(name=name)
        f = Floor.objects.create(building=b, name="1层")
        room = Room.objects.create(floor=f, number="101")
        Bed.objects.create(room=room, number="1")

    items = client.get(
        "/api/beds/", {"building": "2号楼"}, HTTP_X_BUILDING="1号楼"
    ).json()["items"]
    assert {i["building"] for i in items} == {"1号楼"}  # scope 赢，不是空集

    stats = client.get(
        "/api/beds/occupancy/", {"building": "2号楼"}, HTTP_X_BUILDING="1号楼"
    ).json()
    assert [b["building"] for b in stats["buildings"]] == ["1号楼"]
    assert stats["total"]["total"] == 1
