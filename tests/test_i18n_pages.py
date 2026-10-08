"""轻量页双语冒烟 — 2026-09-15 模板批翻译的回归钉。

登录后 GET 六个轻量页，zh 与 en（django_language cookie）各来一遍：
断言 200（模板语法/视图不因翻译包装破损）+ en 下抽样英文文案存在。
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client

PAGES = ["/kitchen/", "/beds/", "/billing/", "/assessments/", "/weekly-order/", "/quick-log/"]

# en 抽样断言（页面标题级）：页 → 英文串
EN_SPOT = {
    "/kitchen/": "Kitchen Board - Today",
    "/beds/": "Occupancy overview",
    "/billing/": "Bills",
    "/assessments/": "Assessment status overview",
    "/weekly-order/": "Pick a resident to start ordering",
    "/quick-log/": "Pick a resident to start logging",
}

ZH_SPOT = {
    "/kitchen/": "食堂今日看板",
    "/beds/": "入住率总览",
    "/billing/": "应收月账单",
    "/assessments/": "评估状态盘点",
    "/weekly-order/": "周选点餐",
    "/quick-log/": "快速记录",
}

# base_light 顶栏导航 7 标签（全部轻量页共享）
NAV_ZH = ["记录", "周选", "床位", "评估", "食堂", "财务", "管理"]
NAV_EN = ["Records", "Weekly Order", "Beds", "Assessments", "Kitchen", "Finance", "Admin"]


@pytest.fixture
def staff_client(db):
    User.objects.create_superuser("i18n_pages_admin", "a@a.com", "pw")
    c = Client()
    c.force_login(User.objects.get(username="i18n_pages_admin"))
    return c


@pytest.mark.django_db
@pytest.mark.parametrize("path", PAGES)
def test_pages_render_zh(staff_client, path):
    resp = staff_client.get(path)
    assert resp.status_code == 200
    assert ZH_SPOT[path].encode() in resp.content
    for w in NAV_ZH:
        assert w.encode() in resp.content


@pytest.mark.django_db
@pytest.mark.parametrize("path", PAGES)
def test_pages_render_en(staff_client, path):
    staff_client.cookies["django_language"] = "en"
    resp = staff_client.get(path)
    assert resp.status_code == 200
    assert EN_SPOT[path].encode() in resp.content
    for w in NAV_EN:
        assert w.encode() in resp.content


@pytest.mark.django_db
def test_lifecycle_page_render_zh_and_en(staff_client):
    """resident_lifecycle 整页迁移钉：zh/en 各渲染一遍，抽侧栏标签与图表系列名。"""
    from datetime import date

    from residents.models import Resident

    r = Resident.objects.create(
        name="档案老人", gender="男", age=88,
        id_card="330100193801010019",
        building="1号楼", floor="1层", room="101",
        admission_date=date(2026, 9, 1),
    )
    resp = staff_client.get(f"/resident/{r.id}/lifecycle/")
    assert resp.status_code == 200
    for spot in ("生命周期档案", "生命周期时间线", "健康趋势", "既往病史",
                 "入住", "档案老人 生命周期档案"):
        assert spot.encode() in resp.content

    staff_client.cookies["django_language"] = "en"
    resp = staff_client.get(f"/resident/{r.id}/lifecycle/")
    assert resp.status_code == 200
    for spot in ("Lifecycle Profile", "Lifecycle Timeline", "Health Trends",
                 "Medical History", "88 yrs old",
                 "Systolic", "Diastolic", "Admission",
                 "档案老人 Lifecycle Profile"):
        assert spot.encode() in resp.content

    # 无事件老人：空态文案仍 bilingual（时间线 empty state）
    r_empty = Resident.objects.create(
        name="空档案老人", gender="女", age=90,
        id_card="330100193801010028",
        building="2号楼", floor="2层", room="202",
    )
    resp = staff_client.get(f"/resident/{r_empty.id}/lifecycle/")
    assert "No records yet".encode() in resp.content
    staff_client.cookies["django_language"] = "zh-hans"
    resp = staff_client.get(f"/resident/{r_empty.id}/lifecycle/")
    assert "暂无记录".encode() in resp.content


# ── admin 筛选器数据值显示层翻译（2026-10-08：OperationLog.action / User.groups）──

def test_admin_filter_data_values_translated(db):
    """en 下 admin 筛选下拉的 DB 数据值（动作/组名）经 gettext 显示英文，
    zh 下保持中文原值（数据本身不动）。"""
    from django.contrib.auth.models import Group
    from auditlog.models import OperationLog

    Group.objects.get_or_create(name="医务组")
    Group.objects.get_or_create(name="护理组")
    OperationLog.objects.create(
        actor_type="staff", actor_name="张三", action="家属代点餐",
        method="POST", path="/api/x", status_code=200,
    )
    OperationLog.objects.create(
        actor_type="family", actor_name="李四", action="点餐OCR识别",
        method="POST", path="/api/y", status_code=200,
    )
    User.objects.create_superuser("flt_admin", "a@a.com", "pw")
    c = Client()
    assert c.login(username="flt_admin", password="pw")

    c.cookies["django_language"] = "en"
    op = c.get("/admin/auditlog/operationlog/").content.decode()
    assert "Family-ordered meal" in op and "Meal order OCR" in op
    assert "家属代点餐" not in op and "点餐OCR识别" not in op
    us = c.get("/admin/auth/user/").content.decode()
    assert "Medical Group" in us and "Nursing Group" in us
    assert "医务组" not in us

    c.cookies["django_language"] = "zh-hans"
    op = c.get("/admin/auditlog/operationlog/").content.decode()
    assert "家属代点餐" in op
    us = c.get("/admin/auth/user/").content.decode()
    assert "医务组" in us


def test_admin_group_list_translated(db):
    """en 下 /admin/auth/group/ 行名（Group.__str__）显示层翻译。"""
    from django.contrib.auth.models import Group

    Group.objects.get_or_create(name="医务组")
    Group.objects.get_or_create(name="院办管理组")
    User.objects.create_superuser("grp_admin", "a@a.com", "pw")
    c = Client()
    assert c.login(username="grp_admin", password="pw")

    c.cookies["django_language"] = "en"
    page = c.get("/admin/auth/group/").content.decode()
    assert "Medical Group" in page and "Administration Group" in page
    assert "医务组" not in page

    c.cookies["django_language"] = "zh-hans"
    page = c.get("/admin/auth/group/").content.decode()
    assert "医务组" in page
