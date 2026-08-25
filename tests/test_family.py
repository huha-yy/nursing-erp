"""家属端（family app）测试 — Q6 重启落地，2026-08-24。

分层（仿 test_billing.py）：
1. 模型 6：token 唯一与 regen / 绑定唯一约束 / 多绑矩阵 / is_family_user /
   cancel 扩签名记 operator（回归钉：不传行为不变）
2. 认证闭合 11：/auth/ 成功换 token / 错密码 / 缺 key / 非家属账号 /
   机器 token 路径 / 坏 token / key 无家属令牌 fail-closed / 停用双路 401 /
   员工 session 进家属 API 401 / 家属 session 打员工 /api/ 401（闭合关键钉）/
   家属与裸账号访问员工页 302 /family/
3. API 数据面 13：overview 契约与范围 / id_card 全 payload 不泄露（红线）/
   欠费聚合 / care 载荷含诊断过敏与 7 日窗 / 未绑定 404 / meals 周视图对齐周一 /
   坏 week_start 400 / billing 形状与截止月 / 他人账单不可见 / 坏 month 400 /
   批量代点归属（ordered_by 服务端生成 + emp 空）/ 重复槽整批 400 零残留 /
   越界整批 403 零残留
4. 写路径 3：cancel 留痕 changed_by / body 自定义 reason / 守卫 403 与 404
5. 页面 8：登录 GET+POST / 错密码重渲染 / 6 页匿名 302 / 员工进家属页弹 login /
   home 渲染且无员工链接 / 改密流程双端生效 / next 外站守卫
6. admin 4：开通建 User+绑定 / 令牌与密码 action / sidebar 家属服务组钉 /
   台账只读

核心红线：家属视角永不出现 id_card / Resident.notes / 他人老人；
家属 session 进不了员工 /api/，员工 session 进不了 /api/family/。
"""

import itertools
import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from family.models import FamilyBinding, FamilyMember, is_family_user

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _erp_key(settings):
    """conftest 的 client fixture 只惠及参数里要它的测试；本模块大量自建
    Client（机器路径/匿名/员工 session），统一在此设置服务间 key。"""
    settings.ERP_API_KEY = "test-api-key"


# ---- 造数工厂 ----


def _resident(**kw):
    from residents.models import Resident

    kw.setdefault("name", "测试老人")
    kw.setdefault("building", "1号楼")
    kw.setdefault("floor", "1层")
    kw.setdefault("room", "101")
    kw.setdefault("care_level", "自理")
    kw.setdefault("id_card", f"3301001948010100{_ids.__next__():04d}")
    return Resident.objects.create(**kw)


def _family(name="王丽华"):
    i = _ids.__next__()
    phone = f"1380000{i:04d}"
    user = User.objects.create_user(username=phone, password="123456")
    fm = FamilyMember.objects.create(user=user, name=name, phone=phone)
    return fm


def _bind(fm, r, relation=FamilyBinding.Relation.CHILD):
    return FamilyBinding.objects.create(family=fm, resident=r, relation=relation)


def _log(r, days_ago=0, detail="协助进食正常", category="feeding"):
    from datetime import date, timedelta

    from residents.models import NursingLog

    return NursingLog.objects.create(
        resident=r, log_date=date.today() - timedelta(days=days_ago),
        category=category, detail=detail, staff_name="护理员小张",
    )


def _order(r, d, meal_type="午餐", status="ordered", ordered_by="前台代点"):
    from meals.models import Dish, MealOrder

    dish, _ = Dish.objects.get_or_create(name=f"测试菜{_ids.__next__()}", category="荤菜")
    o = MealOrder.objects.create(
        resident=r, date=d, meal_type=meal_type, status=status, ordered_by=ordered_by
    )
    o.dishes.add(dish)
    return o, dish


def _machine(fm):
    """机器路径客户端：X-API-Key + X-Family-Token（dl-control 形态）。"""
    return Client(HTTP_X_API_KEY="test-api-key", HTTP_X_FAMILY_TOKEN=fm.token)


def _login_session(fm):
    """家属 session 客户端（家属页 JS 形态）。"""
    c = Client()
    c.force_login(fm.user)
    return c


# ---- 1. 模型层 ----


@pytest.mark.django_db
def test_token_unique_and_regen():
    a, b = _family(), _family()
    assert a.token != b.token and len(a.token) == 32  # token_hex(16)
    old = a.token
    a.regen_token()
    a.refresh_from_db()
    assert a.token != old and len(a.token) == 32
    assert FamilyMember.objects.filter(token=old).count() == 0  # 旧令牌即作废


@pytest.mark.django_db
def test_binding_unique_constraint():
    fm = _family()
    r = _resident()
    _bind(fm, r)
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        FamilyBinding.objects.create(family=fm, resident=r, relation="配偶")


@pytest.mark.django_db
def test_multi_binding_matrix():
    """一位家属绑多位老人（同房两老）＋ 一位老人被多位家属绑（老伴+子女）都合法。"""
    fm = _family()
    r1, r2 = _resident(room="101"), _resident(room="101")
    fm2 = _family("李建国")
    _bind(fm, r1)
    _bind(fm, r2, relation=FamilyBinding.Relation.SPOUSE)
    _bind(fm2, r1, relation=FamilyBinding.Relation.CHILD)
    assert set(fm.bindings.values_list("resident_id", flat=True)) == {r1.id, r2.id}
    assert set(r1.family_bindings.values_list("family__name", flat=True)) == {"王丽华", "李建国"}


@pytest.mark.django_db
def test_is_family_user():
    fm = _family()
    plain = User.objects.create_user(username=f"plain{_ids.__next__()}", password="x")
    staff = User.objects.create_user(username=f"stf{_ids.__next__()}", password="x", is_staff=True)
    assert is_family_user(fm.user) is True
    assert is_family_user(plain) is False
    assert is_family_user(staff) is False
    assert is_family_user(None) is False


@pytest.mark.django_db
def test_cancel_records_operator():
    """cancel 扩签名：operator 落 MealModificationLog.changed_by；不传行为不变（回归钉）。"""
    from datetime import date

    from meals.models import MealModificationLog

    r = _resident()
    o1, _ = _order(r, date(2026, 9, 1))
    o1.cancel("家属代退", operator="家属-王丽华（子女）")
    log1 = MealModificationLog.objects.get(order=o1)
    assert log1.changed_by == "家属-王丽华（子女）"
    assert log1.reason == "家属代退"

    o2, _ = _order(r, date(2026, 9, 2))
    o2.cancel("管理员操作退餐")  # 员工端两处既有调用不传 operator
    log2 = MealModificationLog.objects.get(order=o2)
    assert log2.changed_by == ""


@pytest.mark.django_db
def test_attribution_length_within_limit():
    """归属串 ≤ MealOrder.ordered_by 的 30 字上限（长名字+兄弟姐妹 也不超）。"""
    from family.api import _attribution

    fm = _family(name="欧阳娜娜子轩")  # 6 字姓 + 4 字名
    r = _resident()
    _bind(fm, r, relation=FamilyBinding.Relation.SIBLING)
    s = _attribution(fm, r.id)
    assert len(s) <= 30
    assert s == "家属-欧阳娜娜子轩（兄弟姐妹）"


# ---- 2. 认证闭合 ----


@pytest.mark.django_db
def test_auth_login_ok(client):
    fm = _family()
    r = _resident()
    _bind(fm, r)
    resp = client.post("/api/family/auth/", {"phone": fm.phone, "password": "123456"},
                       content_type="application/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == fm.token
    assert data["name"] == "王丽华"
    assert data["residents"] == [{"id": r.id, "name": r.name, "building": r.building,
                                  "room": r.room, "relation": "子女"}]
    assert "password" not in json.dumps(data)


@pytest.mark.django_db
def test_auth_wrong_password_401(client):
    fm = _family()
    resp = client.post("/api/family/auth/", {"phone": fm.phone, "password": "bad"},
                       content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_auth_missing_api_key_401():
    fm = _family()
    resp = Client().post("/api/family/auth/", {"phone": fm.phone, "password": "123456"},
                         content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_auth_non_family_account_401(client):
    """员工账号凭据正确也不给 token——家属身份由档案说了算。"""
    User.objects.create_user(username="13811112222", password="123456", is_staff=True)
    resp = client.post("/api/family/auth/", {"phone": "13811112222", "password": "123456"},
                       content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_machine_token_path_ok():
    fm = _family()
    _bind(fm, _resident())
    resp = _machine(fm).get("/api/family/overview/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.django_db
def test_machine_bad_token_401(client):
    _family()
    resp = client.get("/api/family/overview/", HTTP_X_FAMILY_TOKEN="deadbeef" * 4)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_api_key_without_family_token_fail_closed(client):
    """只有服务间 key、不带家属令牌 → 401，绝不退化为"全体家属"。"""
    _family()
    resp = client.get("/api/family/overview/")  # conftest client 只带 X-API-Key
    assert resp.status_code == 401


@pytest.mark.django_db
def test_inactive_member_401_both_paths():
    fm = _family()
    _bind(fm, _resident())
    fm.is_active = False
    fm.save(update_fields=["is_active"])
    assert _machine(fm).get("/api/family/overview/").status_code == 401
    assert _login_session(fm).get("/api/family/overview/").status_code == 401


@pytest.mark.django_db
def test_staff_session_rejected_by_family_api():
    """员工 session 无家属档案 → 家属 API 401（身份互不串门）。"""
    staff = User.objects.create_user(username=f"stf{_ids.__next__()}", password="x", is_staff=True)
    c = Client()
    c.force_login(staff)
    assert c.get("/api/family/overview/").status_code == 401
    resp = c.post("/api/family/meal-orders/batch/", [], content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_family_session_blocked_from_staff_api():
    """闭合关键钉：家属 session 打员工 /api/*（读+写）一律 401。"""
    fm = _family()
    r = _resident()
    _bind(fm, r)
    c = _login_session(fm)
    resp = c.get("/api/residents/")
    assert resp.status_code == 401
    resp = c.post("/api/nursing-logs/", {
        "resident_id": r.id, "log_date": "2026-08-24", "category": "feeding", "detail": "越权写入",
    }, content_type="application/json")
    assert resp.status_code == 401
    from residents.models import NursingLog

    assert NursingLog.objects.count() == 0  # 401 且零写入


@pytest.mark.django_db
def test_staff_pages_redirect_family_and_plain_accounts():
    """家属/裸账号（无员工档案）访问员工轻量页 → 302 /family/；匿名仍走 admin 登录。"""
    fm = _family()
    c = _login_session(fm)
    assert c.get("/kitchen/").status_code == 302
    assert c.get("/kitchen/").url == "/family/"

    plain = User.objects.create_user(username=f"plain{_ids.__next__()}", password="x")
    c2 = Client()
    c2.force_login(plain)
    assert c2.get("/billing/").status_code == 302
    assert c2.get("/billing/").url == "/family/"

    anon = Client().get("/kitchen/")
    assert anon.status_code == 302
    assert "/admin/login/" in anon.url


# ---- 3. API 数据面 ----


@pytest.mark.django_db
def test_overview_contract_and_scope():
    fm = _family()
    mine = _resident(name="我妈", room="301")
    _resident(name="别人家", room="302")  # 他家老人：绝不出现在 payload
    _bind(fm, mine)
    _log(mine, days_ago=1)
    data = _machine(fm).get("/api/family/overview/").json()
    assert [row["id"] for row in data] == [mine.id]  # 范围：只有绑定老人
    row = data[0]
    assert row["relation"] == "子女"
    assert row["care_level_display"]
    assert len(row["recent_logs"]) == 1
    assert row["recent_logs"][0]["detail"] == "协助进食正常"
    assert row["arrears"] is None  # 无账单 → 不欠费


@pytest.mark.django_db
def test_id_card_never_leaks():
    """红线：身份证号在所有家属端 payload 中一字不出现。"""
    fm = _family()
    r = _resident(id_card="330100194801019999")
    _bind(fm, r)
    import datetime as dt

    _order(r, dt.date.today())
    dumps = "".join(
        _machine(fm).get(url).content.decode()
        for url in (
            "/api/family/overview/", "/api/family/care/",
            f"/api/family/care/{r.id}/", "/api/family/meals/", "/api/family/billing/",
        )
    )
    assert "id_card" not in dumps
    assert "330100194801019999" not in dumps


@pytest.mark.django_db
def test_overview_arrears_aggregate():

    from billing.models import MonthlyBill

    fm = _family()
    r = _resident()
    _bind(fm, r)
    MonthlyBill.objects.create(resident=r, month="2026-05", bed_fee=800, nursing_fee=300,
                               meal_fee=150, total=1250, status="pending")
    MonthlyBill.objects.create(resident=r, month="2026-06", bed_fee=800, nursing_fee=300,
                               meal_fee=120, total=1220, status="pending")
    MonthlyBill.objects.create(resident=r, month="2026-07", bed_fee=800, nursing_fee=300,
                               meal_fee=100, total=1200, status="settled")
    row = _machine(fm).get("/api/family/overview/").json()[0]
    assert row["arrears"] == {"unpaid_months": 2, "outstanding": 2470.0, "oldest_month": "2026-05"}


@pytest.mark.django_db
def test_care_payload_windows_and_medical_visibility():
    import datetime as dt

    from assessments.models import Assessment
    from residents.models import HealthRecord, MedicationRecord

    fm = _family()
    r = _resident(diagnosis="高血压二期", allergies="青霉素")
    _bind(fm, r)
    _log(r, days_ago=3)
    _log(r, days_ago=30)  # 窗外：不应出现
    Assessment.objects.create(resident=r, assess_date=dt.date.today(), assessor1="张医生",
                              assessor2="李护士", total_score=45, grade=2, status="confirmed",
                              final_level="半护")
    HealthRecord.objects.create(resident=r, record_date=dt.date.today(), blood_pressure="130/85",
                                heart_rate=76)
    MedicationRecord.objects.create(resident=r, medicine_name="络活喜", dosage="5mg",
                                    frequency="qd", start_date=dt.date(2026, 1, 1))
    MedicationRecord.objects.create(resident=r, medicine_name="已停药品", dosage="1mg",
                                    frequency="qd", start_date=dt.date(2025, 1, 1), is_active=False)
    row = _machine(fm).get(f"/api/family/care/?resident_id={r.id}").json()[0]
    assert row["diagnosis"] == "高血压二期"  # 健康档案对家属开放（产品决策）
    assert row["allergies"] == "青霉素"
    assert len(row["logs_7d"]) == 1
    assert len(row["medications"]) == 1 and row["medications"][0]["medicine_name"] == "络活喜"
    assert row["assessment"]["final_level"] == "半护"
    assert row["health_records"][0]["blood_pressure"] == "130/85"


@pytest.mark.django_db
def test_care_unbound_resident_404():
    fm = _family()
    _bind(fm, _resident())
    other = _resident()  # 存在但未绑定 → 404 不泄露存在性
    resp = _machine(fm).get(f"/api/family/care/?resident_id={other.id}")
    assert resp.status_code == 404
    assert _machine(fm).get("/api/family/care/?resident_id=99999").status_code == 404


@pytest.mark.django_db
def test_meals_week_view_aligns_monday():
    import datetime as dt

    from meals.models import WeekMenu

    fm = _family()
    r = _resident()
    _bind(fm, r)
    monday = dt.date(2026, 8, 24)  # 周一
    o, dish = _order(r, monday, ordered_by="家属-王丽华（子女）")
    menu = WeekMenu.objects.create(week_start=monday, day="周一", meal_type="午餐")
    menu.dishes.add(dish)
    resp = _machine(fm).get("/api/family/meals/?week_start=2026-08-26")  # 周三 → 对齐周一
    data = resp.json()
    assert data["week_start"] == "2026-08-24"
    assert data["week_end"] == "2026-08-30"
    assert [x["id"] for x in data["residents"]] == [r.id]
    assert data["menu"][0]["dishes"][0]["name"] == dish.name
    assert data["orders"][0]["ordered_by"].startswith("家属-")


@pytest.mark.django_db
def test_meals_bad_week_start_400(client):
    fm = _family()
    resp = client.get("/api/family/meals/?week_start=not-a-date", HTTP_X_FAMILY_TOKEN=fm.token)
    assert resp.status_code == 400


@pytest.mark.django_db
def test_billing_shape_and_cutoff():
    from billing.models import MonthlyBill

    fm = _family()
    r = _resident()
    _bind(fm, r)
    MonthlyBill.objects.create(resident=r, month="2026-06", bed_fee=800, nursing_fee=300,
                               meal_fee=150, total=1250, status="settled", settled_by="王会计")
    MonthlyBill.objects.create(resident=r, month="2026-07", bed_fee=800, nursing_fee=300,
                               meal_fee=100, total=1200, status="pending")
    data = _machine(fm).get("/api/family/billing/?month=2026-07").json()
    assert data["month"] == "2026-07"
    row = data["residents"][0]
    assert [b["month"] for b in row["bills"]] == ["2026-07", "2026-06"]
    b0 = row["bills"][0]
    assert set(b0) >= {"month", "bed_fee", "nursing_fee", "meal_fee", "total",
                       "status", "status_display", "settled_at", "settled_by", "note"}
    assert b0["total"] == 1200.0
    assert row["bills"][1]["settled_by"] == "王会计"  # _bill_out 形状（与员工端同构）
    assert row["arrears"]["outstanding"] == 1200.0
    # 截止月：只看 2026-06 时 07 月不可见
    data2 = _machine(fm).get("/api/family/billing/?month=2026-06").json()
    assert [b["month"] for b in data2["residents"][0]["bills"]] == ["2026-06"]


@pytest.mark.django_db
def test_billing_other_family_invisible():
    from billing.models import MonthlyBill

    fm = _family()
    mine = _resident()
    _bind(fm, mine)
    other = _resident()
    MonthlyBill.objects.create(resident=other, month="2026-07", bed_fee=800, nursing_fee=300,
                               meal_fee=100, total=1200, status="pending")
    data = _machine(fm).get("/api/family/billing/").json()
    assert [x["resident"]["id"] for x in data["residents"]] == [mine.id]
    assert "1200" not in json.dumps(data)  # 他人账单金额不可见


@pytest.mark.django_db
def test_billing_bad_month_400(client):
    fm = _family()
    resp = client.get("/api/family/billing/?month=2026-7", HTTP_X_FAMILY_TOKEN=fm.token)
    assert resp.status_code == 400


@pytest.mark.django_db
def test_batch_attribution_server_generated():

    fm = _family()
    r = _resident()
    _bind(fm, r)
    from meals.models import Dish

    d1 = Dish.objects.create(name="红烧肉", category="荤菜")
    d2 = Dish.objects.create(name="炒青菜", category="素菜")
    resp = _machine(fm).post("/api/family/meal-orders/batch/", [
        {"resident_id": r.id, "date": "2026-09-01", "meal_type": "午餐",
         "dish_ids": [d1.id, d2.id], "special_requests": "少油", "ordered_by": "冒名的员工"},
    ], content_type="application/json")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    from meals.models import MealOrder

    o = MealOrder.objects.get(resident=r, date="2026-09-01")
    assert o.ordered_by == "家属-王丽华（子女）"  # 入参 ordered_by 被无视，服务端生成
    assert o.ordered_by_emp is None or o.ordered_by_emp == ""
    assert o.special_requests == "少油"
    assert set(o.dishes.values_list("name", flat=True)) == {"红烧肉", "炒青菜"}


@pytest.mark.django_db
def test_batch_duplicate_slot_400_zero_residue():
    import datetime as dt

    fm = _family()
    r = _resident()
    _bind(fm, r)
    _order(r, dt.date(2026, 9, 1), meal_type="午餐")  # 该槽已被院方代点
    resp = _machine(fm).post("/api/family/meal-orders/batch/", [
        {"resident_id": r.id, "date": "2026-09-01", "meal_type": "午餐", "dish_ids": []},
        {"resident_id": r.id, "date": "2026-09-02", "meal_type": "晚餐", "dish_ids": []},
    ], content_type="application/json")
    assert resp.status_code == 400
    from meals.models import MealOrder

    assert MealOrder.objects.filter(date="2026-09-02").count() == 0  # 整批原子，零残留


@pytest.mark.django_db
def test_batch_cross_family_403_zero_residue():
    fm = _family()
    mine = _resident()
    other = _resident()  # 别人家的老人
    _bind(fm, mine)
    resp = _machine(fm).post("/api/family/meal-orders/batch/", [
        {"resident_id": mine.id, "date": "2026-09-01", "meal_type": "午餐", "dish_ids": []},
        {"resident_id": other.id, "date": "2026-09-01", "meal_type": "午餐", "dish_ids": []},
    ], content_type="application/json")
    assert resp.status_code == 403
    from meals.models import MealOrder

    assert MealOrder.objects.count() == 0  # 整批拒绝，零残留


# ---- 4. 写路径 ----


@pytest.mark.django_db
def test_cancel_leaves_attribution_trail():
    import datetime as dt

    fm = _family()
    r = _resident()
    _bind(fm, r)
    o, _ = _order(r, dt.date(2026, 9, 3))
    resp = _machine(fm).post(f"/api/family/meal-orders/{o.id}/cancel/", {},
                             content_type="application/json")
    assert resp.status_code == 200
    o.refresh_from_db()
    assert o.status == "cancelled"
    from meals.models import MealModificationLog

    log = MealModificationLog.objects.get(order=o)
    assert log.changed_by == "家属-王丽华（子女）"
    assert log.reason == "家属代退"  # 缺省原因


@pytest.mark.django_db
def test_cancel_body_reason():
    import datetime as dt

    fm = _family()
    r = _resident()
    _bind(fm, r)
    o, _ = _order(r, dt.date(2026, 9, 3))
    _machine(fm).post(f"/api/family/meal-orders/{o.id}/cancel/",
                      {"reason": "老人牙口不好改天再吃"}, content_type="application/json")
    from meals.models import MealModificationLog

    assert MealModificationLog.objects.get(order=o).reason == "老人牙口不好改天再吃"


@pytest.mark.django_db
def test_cancel_guards():
    import datetime as dt

    fm = _family()
    r = _resident()
    _bind(fm, r)
    stranger_order, _ = _order(_resident(), dt.date(2026, 9, 3))  # 他人订单
    assert _machine(fm).post(f"/api/family/meal-orders/{stranger_order.id}/cancel/",
                             {}, content_type="application/json").status_code == 403
    assert _machine(fm).post("/api/family/meal-orders/99999/cancel/",
                             {}, content_type="application/json").status_code == 404


# ---- 5. 页面 ----


@pytest.mark.django_db
def test_login_get_post_flow():
    fm = _family()
    r = _resident()
    _bind(fm, r)
    c = Client()
    assert c.get("/family/login/").status_code == 200
    resp = c.post("/family/login/", {"phone": fm.phone, "password": "123456"})
    assert resp.status_code == 302 and resp.url == "/family/"
    assert c.get("/family/").status_code == 200  # session 已建立
    assert c.get("/api/family/overview/").status_code == 200  # 页面 JS 同源可用


@pytest.mark.django_db
def test_login_wrong_password_rerenders():
    fm = _family()
    resp = Client().post("/family/login/", {"phone": fm.phone, "password": "bad"})
    assert resp.status_code == 200
    assert "手机号或密码错误" in resp.content.decode()


@pytest.mark.django_db
def test_login_pages_cross_linked():
    """双入口互链（2026-08-25）：后台登录页给家属入口，家属页给员工入口。"""
    resp = Client().get("/admin/login/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "/family/login/" in body and "家属服务登录" in body

    resp = Client().get("/family/login/")
    assert "/admin/login/" in resp.content.decode()


@pytest.mark.django_db
def test_all_pages_anonymous_redirect_to_login():
    urls = ("/family/", "/family/care/", "/family/care/1/", "/family/order/",
            "/family/billing/", "/family/password/")
    for url in urls:
        resp = Client().get(url)
        assert resp.status_code == 302, url
        assert resp.url.startswith("/family/login/?next="), url


@pytest.mark.django_db
def test_staff_bounced_from_family_pages():
    staff = User.objects.create_user(username=f"stf{_ids.__next__()}", password="x", is_staff=True)
    c = Client()
    c.force_login(staff)
    resp = c.get("/family/")
    assert resp.status_code == 302
    assert resp.url.startswith("/family/login/")


@pytest.mark.django_db
def test_home_renders_without_staff_links():
    fm = _family()
    _bind(fm, _resident())
    html = _login_session(fm).get("/family/").content.decode()
    assert "/admin/" not in html
    assert "家属服务" in html  # 家属导航在位
    for nav in ("照护", "点餐", "账单", "改密码"):
        assert nav in html


@pytest.mark.django_db
def test_password_change_flow():
    fm = _family()
    c = _login_session(fm)
    resp = c.post("/family/password/", {
        "old_password": "123456", "new_password1": "newpass9", "new_password2": "newpass9",
    })
    assert resp.status_code == 302 and resp.url == "/family/password/?changed=1"
    assert c.get("/family/").status_code == 200  # update_session_auth_hash：改完不掉线
    fm.user.refresh_from_db()
    assert fm.user.check_password("newpass9")


@pytest.mark.django_db
def test_login_next_open_redirect_guard():
    fm = _family()
    resp = Client().post("/family/login/", {
        "phone": fm.phone, "password": "123456", "next": "https://evil.example.com",
    })
    assert resp.status_code == 302
    assert resp.url == "/family/"  # 外站 next 一律忽略


# ---- 6. admin ----


@pytest.mark.django_db
def test_admin_provision_creates_user_and_bindings(client):
    superuser = User.objects.create_superuser("rootsup", "r@x.com", "123456")
    client.force_login(superuser)
    r = _resident()
    resp = client.post("/admin/family/familymember/add/", {
        "name": "李建国", "phone": "13900000002", "relation": "子女", "residents": str(r.id),
    })
    assert resp.status_code == 302
    fm = FamilyMember.objects.get(phone="13900000002")
    assert User.objects.filter(username="13900000002").exists()
    assert fm.user.check_password("123456")  # 初始密码
    assert fm.bindings.filter(resident=r, relation="子女").exists()


@pytest.mark.django_db
def test_admin_provision_rejects_taken_phone(client):
    """手机号与既有员工/家属撞号 → 表单报错，不开半套账号。"""
    superuser = User.objects.create_superuser("rootsup2", "r2@x.com", "123456")
    client.force_login(superuser)
    User.objects.create_user(username="13800000009", password="x")
    resp = client.post("/admin/family/familymember/add/", {
        "name": "撞号者", "phone": "13800000009", "relation": "子女", "residents": "1",
    })
    assert resp.status_code == 200  # 重渲染表单
    assert "已被账号占用" in resp.content.decode()
    assert FamilyMember.objects.filter(phone="13800000009").count() == 0


@pytest.mark.django_db
def test_admin_regen_and_reset_actions(client):
    superuser = User.objects.create_superuser("rootsup3", "r3@x.com", "123456")
    client.force_login(superuser)
    fm = _family()
    old = fm.token
    resp = client.post("/admin/family/familymember/", data={
        "action": "action_regen_token", "_selected_action": str(fm.id),
    })
    assert resp.status_code == 302
    fm.refresh_from_db()
    assert fm.token != old

    client.post("/admin/family/familymember/", data={
        "action": "action_reset_password", "_selected_action": str(fm.id),
    })
    fm.user.refresh_from_db()
    assert fm.user.check_password("123456")


@pytest.mark.django_db
def test_sidebar_pins_family_group():
    """UNFOLD 点名制 sidebar：家属服务组必须在册（床组曾静默漏配）。"""
    from django.conf import settings

    groups = {g["title"]: g for g in settings.UNFOLD["SIDEBAR"]["navigation"]}
    assert "家属服务" in groups
    links = {i["link"] for i in groups["家属服务"]["items"]}
    assert links == {"/admin/family/familymember/", "/admin/family/familybinding/"}


@pytest.mark.django_db
def test_binding_ledger_readonly(client):
    superuser = User.objects.create_superuser("rootsup4", "r4@x.com", "123456")
    client.force_login(superuser)
    fm = _family()
    r = _resident()
    _bind(fm, r)
    resp = client.get("/admin/family/familybinding/")
    assert resp.status_code == 200
    assert "familybinding/add/" not in resp.content.decode()
    # 只读台账仍可搜索定位"谁能看到谁"
    assert fm.name in resp.content.decode() or r.name in resp.content.decode()
