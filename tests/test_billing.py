"""应收月账单（billing）测试 — 阶段二 Q3，2026-08-21。

分层（仿 test_beds.py）：
1. 模型层 9：种子默认值 / 价目查询与缺行 fail-loud / 出账组成 /
   无点餐不造幽灵月结行（回归钉）/ paid 冻结 / 无床餐费收尾账单 /
   减免重算 / 核销幂等+FK 自动挂 / 撤销核销全清
2. 服务层 2：批量范围与计数 / 欠费聚合
3. API 4：列表契约钉+scope / generate 校验 / settle 守卫 / summary 勾稽
4. 页面 2：匿名跳转+登录渲染 / POST 出账+核销
5. admin 1：楼栋过滤 + paid 只读三费

核心不变式：meals/ 一行不改——当月无点餐的老人绝不产生新 MealFinance 行。
"""

import itertools

import pytest
from django.contrib.auth.models import User

_ids = itertools.count(1)


def _resident(**kw):
    from residents.models import Resident

    kw.setdefault("name", "测试老人")
    kw.setdefault("building", "1号楼")
    kw.setdefault("floor", "1层")
    kw.setdefault("room", "101")
    kw.setdefault("care_level", "自理")
    kw.setdefault("id_card", f"33010019480101000{_ids.__next__():03d}")
    return Resident.objects.create(**kw)


def _bed(building="1号楼", floor="1层", room="101", number="1"):
    from beds.models import Bed, Building, Floor, Room

    b, _ = Building.objects.get_or_create(name=building)
    f, _ = Floor.objects.get_or_create(building=b, name=floor)
    r, _ = Room.objects.get_or_create(floor=f, number=room)
    bed, _ = Bed.objects.get_or_create(room=r, number=number)
    return bed


def _order(resident, date, meal_type="午餐"):
    from meals.models import MealOrder

    return MealOrder.objects.create(resident=resident, date=date, meal_type=meal_type)


def _employee(name, building=""):
    user = User.objects.create_user(username=f"emp{_ids.__next__()}", password="x")
    from staff.models import Employee

    return Employee.objects.create(
        user=user, name=name, dept="财务科", building=building, phone="1"
    )


# ---- 1. 模型层 ----


@pytest.mark.django_db
def test_seed_default_values():
    """种子迁移钉：0002_seed_fee_rules 的演示默认值（后台可改，此处只钉初始态）"""
    from billing.models import FeeRule

    def amount(fee_type, key=""):
        return FeeRule.get_amount(fee_type, key)

    assert amount("bed") == 800
    assert amount("nursing", "自理") == 300
    assert amount("nursing", "半护") == 1200
    assert amount("nursing", "全护") == 2000
    assert amount("nursing", "失智") == 2400
    assert amount("meal") == 15
    assert FeeRule.objects.count() == 6


@pytest.mark.django_db
def test_feerule_missing_fail_loud():
    """价目缺行 → FeeRuleMissing（fail-loud，中文报错指引后台配置）"""
    from billing.models import FeeRule, FeeRuleMissing

    FeeRule.objects.filter(fee_type="nursing", key="半护").delete()
    with pytest.raises(FeeRuleMissing, match="价目表缺行"):
        FeeRule.get_nursing_fee("半护")
    FeeRule.objects.filter(fee_type="bed").delete()
    with pytest.raises(FeeRuleMissing, match="价目表"):
        FeeRule.get_bed_fee()


@pytest.mark.django_db
def test_generate_month_composition():
    """出账组成：半护在住 + 3 单退 1 → 床位 800 + 护理 1200 + 餐费 30"""
    from billing.models import MonthlyBill

    resident = _resident(care_level="半护")
    resident.bed = _bed()
    resident.save()
    orders = [_order(resident, d) for d in ("2026-08-01", "2026-08-02", "2026-08-03")]
    orders[1].cancel()

    bill = MonthlyBill.generate_month(resident, "2026-08")
    assert bill.bed_fee == 800 and bill.nursing_fee == 1200
    assert bill.meal_fee == 30  # (3-1) × 15
    assert bill.total == 2030
    assert bill.status == MonthlyBill.Status.PENDING


@pytest.mark.django_db
def test_no_orders_no_phantom_finance_row():
    """回归钉：无点餐老人绝不产生 0 元 MealFinance 行（老 /finance/ 数据面不变）"""
    from billing.models import MonthlyBill
    from meals.models import MealFinance

    resident = _resident()
    resident.bed = _bed()
    resident.save()
    bill = MonthlyBill.generate_month(resident, "2026-08")
    assert bill.meal_fee == 0
    assert not MealFinance.objects.filter(resident=resident).exists()


@pytest.mark.django_db
def test_paid_bill_frozen_then_unsettle_refreshes():
    """已缴费账单冻结：再生成原样返回；撤销核销后再生成才刷新"""
    from billing.models import MonthlyBill

    resident = _resident()
    resident.bed = _bed()
    resident.save()
    bill = MonthlyBill.generate_month(resident, "2026-08")
    assert bill.total == 1100  # 800 + 300(自理) + 0
    bill.settle(operator="出纳")

    # 价目改了也不会动已缴费账单
    from billing.models import FeeRule

    FeeRule.objects.filter(fee_type="bed").update(monthly_amount=999)
    frozen = MonthlyBill.generate_month(resident, "2026-08")
    assert frozen.total == 1100 and frozen.status == MonthlyBill.Status.PAID

    # 修正流程：撤销核销 → 再生成 → 金额刷新
    frozen.unsettle()
    refreshed = MonthlyBill.generate_month(resident, "2026-08")
    assert refreshed.total == 1299  # 999 + 300
    assert refreshed.status == MonthlyBill.Status.PENDING


@pytest.mark.django_db
def test_no_bed_meal_only_bill():
    """无床老人（已离院）当月有点餐 → 收尾账单：床位/护理 0，餐费照算"""
    from billing.models import MonthlyBill

    resident = _resident()  # bed 为空
    _order(resident, "2026-08-05")
    bill = MonthlyBill.generate_month(resident, "2026-08")
    assert bill.bed_fee == 0 and bill.nursing_fee == 0 and bill.meal_fee == 15
    assert bill.total == 15


@pytest.mark.django_db
def test_manual_discount_recomputes_total():
    """admin 手工减免：改三费保存即重算 total（save() 路径）"""
    from billing.models import MonthlyBill

    resident = _resident()
    resident.bed = _bed()
    resident.save()
    bill = MonthlyBill.generate_month(resident, "2026-08")
    bill.bed_fee = 700  # 减免 100
    bill.save()
    bill.refresh_from_db()
    assert bill.total == 1000  # 700 + 300


@pytest.mark.django_db
def test_settle_idempotent_and_staff_fk_autolink():
    """核销幂等 + StaffFkMixin 自动挂核销人档案（唯一姓名）"""
    from billing.models import MonthlyBill

    emp = _employee("李会计")
    resident = _resident()
    resident.bed = _bed()
    resident.save()
    bill = MonthlyBill.generate_month(resident, "2026-08")
    bill.settle(operator="李会计", note="8月缴清")
    first_at = bill.settled_at

    assert bill.status == MonthlyBill.Status.PAID
    assert bill.settled_by == "李会计"
    assert bill.settled_by_emp_id == emp.id
    assert bill.note == "8月缴清"

    bill.settle(operator="再核销")  # 幂等：paid 直接返回
    bill.refresh_from_db()
    assert bill.settled_at == first_at
    assert bill.settled_by == "李会计"  # 未被覆盖


@pytest.mark.django_db
def test_unsettle_clears_all():
    resident = _resident()
    resident.bed = _bed()
    resident.save()

    from billing.models import MonthlyBill

    bill = MonthlyBill.generate_month(resident, "2026-08")
    bill.settle(operator="李会计")
    bill.unsettle()

    assert bill.status == MonthlyBill.Status.PENDING
    assert bill.settled_at is None
    assert bill.settled_by == "" and bill.settled_by_emp_id is None
    bill.unsettle()  # 幂等
    assert bill.status == MonthlyBill.Status.PENDING


# ---- 2. 服务层 ----


@pytest.mark.django_db
def test_generate_month_bills_scope_and_atomic_rollback():
    """批量范围 = 在住 ∪ 当月月结行 ∪ 当月点餐；缺价目 atomic 整批回滚"""
    from billing.models import FeeRule, MonthlyBill
    from billing.services import generate_month_bills

    in_bed = _resident(name="在住甲", room="101")
    in_bed.bed = _bed(room="101")
    in_bed.save()
    in_bed2 = _resident(name="在住乙", room="102")
    in_bed2.bed = _bed(room="102")
    in_bed2.save()
    departed_with_orders = _resident(name="离院丙", room="103")  # 无床有点餐 → 收尾账单
    _order(departed_with_orders, "2026-08-10")
    _resident(name="无关丁", room="104")  # 无床无点餐 → 不出账

    result = generate_month_bills("2026-08")
    assert result["generated"] == 3 and result["skipped_paid"] == 0
    assert MonthlyBill.objects.count() == 3
    assert result["total"] == 2215  # (800+300)×2 在住 + 15×1 离院收尾

    # building 过滤
    other = _resident(name="他楼戊", building="2号楼", room="201")
    other.bed = _bed(building="2号楼", room="201")
    other.save()
    assert generate_month_bills("2026-08", building="2号楼")["generated"] == 1

    # 缺价目 → fail-loud + 整批回滚（新月期一条都不留）
    FeeRule.objects.all().delete()
    with pytest.raises(Exception, match="价目表缺行"):
        generate_month_bills("2026-09")
    assert MonthlyBill.objects.filter(month="2026-09").count() == 0


@pytest.mark.django_db
def test_arrears_aggregation():
    """欠费聚合：unpaid_months / oldest_month / outstanding + month 截止"""
    from billing.models import MonthlyBill
    from billing.services import arrears_stats

    r1 = _resident(name="欠两月")
    r2 = _resident(name="欠一月")
    # 注：save() 会以三费重算 total——合成数据把金额放 bed_fee
    MonthlyBill.objects.create(resident=r1, month="2026-07", bed_fee=1100)
    MonthlyBill.objects.create(resident=r1, month="2026-08", bed_fee=1100)
    MonthlyBill.objects.create(resident=r2, month="2026-08", bed_fee=1200)
    MonthlyBill.objects.create(
        resident=r2, month="2026-09", bed_fee=1300, status="paid"
    )  # 已缴不计

    stats = arrears_stats(month="2026-08")
    assert stats["resident_count"] == 2
    assert stats["total_outstanding"] == 1100 + 1100 + 1200
    row1 = next(r for r in stats["rows"] if r["resident__name"] == "欠两月")
    assert row1["unpaid_months"] == 2 and row1["oldest_month"] == "2026-07"
    assert row1["outstanding"] == 2200
    row2 = next(r for r in stats["rows"] if r["resident__name"] == "欠一月")
    assert row2["unpaid_months"] == 1 and row2["oldest_month"] == "2026-08"

    # 截止 2026-07：只看 7 月及以前
    early = arrears_stats(month="2026-07")
    assert early["resident_count"] == 1
    assert early["rows"][0]["outstanding"] == 1100

    # building 过滤
    assert arrears_stats(month="2026-08", building="2号楼")["resident_count"] == 0


# ---- 3. API ----


@pytest.fixture
def api_setup(db):
    """两楼各一位在住老人 + 台账楼栋记录（X-Building 校验用）+ 已出账"""
    from billing.models import MonthlyBill
    from billing.services import generate_month_bills

    r1 = _resident(name="一号老人", room="101")
    r1.bed = _bed(room="101")
    r1.save()
    r2 = _resident(name="二号老人", building="2号楼", room="201")
    r2.bed = _bed(building="2号楼", room="201")
    r2.save()
    generate_month_bills("2026-08")
    return r1, r2, MonthlyBill.objects.get(resident=r1, month="2026-08")


@pytest.mark.django_db
def test_api_list_contract_and_scoping(client, api_setup):
    """列表契约钉（字段集）+ X-Building scope（含 percent-encode 头）"""
    r1, _r2, _bill = api_setup
    items = client.get("/api/billing/", {"month": "2026-08"}).json()["items"]
    assert len(items) == 2
    assert set(items[0]) == {
        "id", "resident_id", "resident_name", "building", "room", "month",
        "bed_fee", "nursing_fee", "meal_fee", "total", "status",
        "status_display", "settled_at", "settled_by", "note",
    }
    assert items[0]["total"] == 1100.0  # 800 + 300(自理) + 0

    for header in ("1号楼", "1%E5%8F%B7%E6%A5%BC"):  # 裸中文与编码等价（线上契约）
        scoped = client.get("/api/billing/", {"month": "2026-08"}, HTTP_X_BUILDING=header)
        assert [i["resident_id"] for i in scoped.json()["items"]] == [r1.id]


@pytest.mark.django_db
def test_api_generate_validation_and_count(client, api_setup):
    """generate：month 格式 400 fail-loud；正常返回计数（财务全院口径）"""
    _r1, r2, _bill = api_setup
    bad = client.post("/api/billing/generate/?month=2026-8")
    assert bad.status_code == 400 and "YYYY-MM" in bad.json()["detail"]

    ok = client.post("/api/billing/generate/?month=2026-08").json()
    assert ok["generated"] == 2 and ok["skipped_paid"] == 0

    one = client.post(f"/api/billing/generate/?month=2026-08&resident_id={r2.id}").json()
    assert one["generated"] == 1


@pytest.mark.django_db
def test_api_settle_guards(client, api_setup):
    """settle：缺失 404 / 跨楼 403 / 正常核销（key 路径 operator=api）/ 幂等"""
    _r1, _r2, bill = api_setup
    # 空 JSON 体（无 body 参数的裸 POST 走 multipart 会先被 ninja 拦 400——契约
    # 是"合法空体 + 缺 id → 404"）
    assert (
        client.post("/api/billing/99999/settle/", content_type="application/json").status_code
        == 404
    )

    cross = client.post(
        f"/api/billing/{bill.id}/settle/",
        content_type="application/json", HTTP_X_BUILDING="2号楼",
    )
    assert cross.status_code == 403

    ok = client.post(
        f"/api/billing/{bill.id}/settle/", {"note": "现金"}, content_type="application/json"
    ).json()
    assert ok["status"] == "paid" and ok["settled_by"] == "api" and ok["note"] == "现金"

    again = client.post(
        f"/api/billing/{bill.id}/settle/",
        {"settled_by": "别人"}, content_type="application/json",
    ).json()
    assert again["settled_by"] == "api"  # 幂等：不覆盖

    unset = client.post(f"/api/billing/{bill.id}/unsettle/", HTTP_X_BUILDING="1号楼").json()
    assert unset["status"] == "pending" and unset["settled_at"] is None


@pytest.mark.django_db
def test_api_summary_scoped_and_unsettle_back_to_pending(client, api_setup):
    """summary 三额勾稽（scope 生效）"""
    _r1, _r2, bill = api_setup
    s = client.get("/api/billing/summary/", {"month": "2026-08"}).json()
    assert s["count"] == 2 and s["receivable"] == 2200.0
    assert s["received"] == 0.0 and s["outstanding"] == 2200.0

    client.post(f"/api/billing/{bill.id}/settle/", content_type="application/json")
    s2 = client.get("/api/billing/summary/", {"month": "2026-08"}).json()
    assert s2["received"] == 1100.0 and s2["outstanding"] == 1100.0
    assert s2["paid_count"] == 1

    # 楼长 scope 只看本楼
    scoped = client.get(
        "/api/billing/summary/", {"month": "2026-08"}, HTTP_X_BUILDING="2号楼"
    ).json()
    assert scoped["count"] == 1 and scoped["receivable"] == 1100.0

    # 欠费名单：核销后离场，撤销后回来
    arr = client.get("/api/billing/arrears/", {"month": "2026-08"}).json()
    assert arr["resident_count"] == 1
    client.post(f"/api/billing/{bill.id}/unsettle/")
    assert client.get("/api/billing/arrears/", {"month": "2026-08"}).json()[
        "resident_count"
    ] == 2


# ---- 4. 页面 /billing/ ----


@pytest.mark.django_db
def test_billing_page_anonymous_redirect_and_logged_in(client, api_setup):
    resp = client.get("/billing/")
    assert resp.status_code == 302 and "/admin/login/" in resp["Location"]

    user = User.objects.create_user(username="viewer", password="x")
    client.force_login(user)
    page = client.get("/billing/", {"month": "2026-08"})
    assert page.status_code == 200
    html = page.content.decode()
    assert "应收月账单" in html and "2026-08" in html and "¥1100" in html


@pytest.mark.django_db
def test_billing_page_post_generate_and_settle(client, api_setup):
    """POST generate 出账 + POST settle 落库（核销人=session 员工姓名）"""
    from billing.models import MonthlyBill

    emp = _employee("王出纳")
    client.force_login(emp.user)

    # 新月份出账
    resp = client.post("/billing/", {"action": "generate", "month": "2026-07"})
    assert resp.status_code == 302
    assert MonthlyBill.objects.filter(month="2026-07").count() == 2

    bill = MonthlyBill.objects.get(resident=api_setup[0], month="2026-07")
    resp = client.post("/billing/", {"action": "settle", "bill_id": bill.id, "month": "2026-07"})
    assert resp.status_code == 302
    bill.refresh_from_db()
    assert bill.status == MonthlyBill.Status.PAID
    assert bill.settled_by == "王出纳" and bill.settled_by_emp_id == emp.id


# ---- 5. admin ----


@pytest.mark.django_db
def test_admin_scoped_queryset_and_paid_readonly(api_setup):
    """admin：楼栋过滤 queryset + 已缴费三费/老人/账期只读"""
    from django.contrib.admin import site

    from billing.admin import MonthlyBillAdmin
    from billing.models import MonthlyBill

    _r1, _r2, bill = api_setup

    boss = User.objects.create_user(username="boss", password="x", is_superuser=True)
    b1_head = _employee("一号楼长", building="1号楼")

    class _Req:
        def __init__(self, user):
            self.user = user

    admin_inst = MonthlyBillAdmin(MonthlyBill, site)
    assert admin_inst.get_queryset(_Req(boss)).count() == 2
    assert admin_inst.get_queryset(_Req(b1_head.user)).count() == 1  # 只见 1号楼

    # pending：三费可编辑
    ro = admin_inst.get_readonly_fields(_Req(boss), bill)
    assert set(ro) == {"total", "settled_at"}

    # paid：冻结金额字段
    bill.settle(operator="出纳")
    ro_paid = admin_inst.get_readonly_fields(_Req(boss), bill)
    assert {"resident", "month", "bed_fee", "nursing_fee", "meal_fee"} <= set(ro_paid)
