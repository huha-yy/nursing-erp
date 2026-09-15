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
