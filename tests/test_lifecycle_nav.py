"""入离院记录导航钉 — 2026-08-26（当日二轮：收拢为三级目录）.

用户在床位看板发现二号楼空闲床（杨国华身故离院释放），追问入离院记录为何
没有查询入口：DischargeRecord / TransferRecord 两张 admin 表一直存在，但
UNFOLD 点名制 sidebar 漏配导致导航不可达。二轮按用户要求收拢为一个
「入离院记录」父目录，下挂 入住/离院/转区 三个子项。本文件钉住：

1. sidebar 老人照护组的入离院三级目录在册且父项带 link
   （UNFOLD sites.py 丢弃无 link 项——嵌套整枝消失的坑）
2. 离院/转区记录表补列（楼栋/原因）生效；老人档案含入住日期列
3. 入住记录（AdmissionRecord 代理模型）只读台账：列头/倒序/无新增
4. 覆写的 app_list.html 真渲染出嵌套子项
5. 三级目录可折叠：默认收起、停在子页自动展开（当日三轮）
6. 全站侧栏规范钉（当日四轮整理）：无单项组 / 平铺≤7条才收拢 /
   三级父项 2~4 子必带 link / 餐费对账归膳食组、异常记录并照护组
"""

import re

import pytest
from django.contrib.auth.models import User


def _collect_links(items):
    """递归收集导航树所有 link（含嵌套 item.items）。"""
    links = set()
    for item in items:
        if item.get("link"):
            links.add(item["link"])
        links |= _collect_links(item.get("items", []))
    return links


@pytest.mark.django_db
def test_sidebar_pins_lifecycle_links():
    """UNFOLD 点名制 sidebar：入离院三级目录必须在册（床组曾静默漏配）。"""
    from django.conf import settings

    groups = {g["title"]: g for g in settings.UNFOLD["SIDEBAR"]["navigation"]}
    assert "老人照护" in groups
    items = {i["title"]: i for i in groups["老人照护"]["items"]}
    # 父项「入离院记录」必须带 link——UNFOLD sites.py 丢弃无 link 项，嵌套会整枝消失
    parent = items["入离院记录"]
    assert parent["link"] == "/admin/residents/admissionrecord/"
    sub_links = _collect_links([parent])
    assert sub_links == {
        "/admin/residents/admissionrecord/",
        "/admin/residents/dischargerecord/",
        "/admin/residents/transferrecord/",
    }


@pytest.mark.django_db
def test_discharge_changelist_columns(client):
    """离院记录表：新列（楼栋/原因）渲染 + 行数据可见。"""
    from residents.models import DischargeRecord, Resident

    superuser = User.objects.create_superuser("lcsup1", "s1@x.com", "123456")
    client.force_login(superuser)
    r = Resident.objects.create(
        name="测试老人", building="1号楼", floor="1层", room="101",
        id_card="330100194801019999", admission_date="2026-01-05",
    )
    DischargeRecord.objects.create(
        resident=r, discharge_type="身故", discharge_date="2026-07-20", reason="因病离世",
    )
    resp = client.get("/admin/residents/dischargerecord/")
    assert resp.status_code == 200
    body = resp.content.decode()
    for col in ("离院类型", "离院日期", "楼栋", "原因"):
        assert col in body
    assert "因病离世" in body and "1号楼" in body


@pytest.mark.django_db
def test_transfer_changelist_columns(client):
    """转区记录表：新列（楼栋/原因）渲染 + 长原因截断。"""
    from residents.models import Resident, TransferRecord

    superuser = User.objects.create_superuser("lcsup2", "s2@x.com", "123456")
    client.force_login(superuser)
    r = Resident.objects.create(
        name="转区老人", building="2号楼", floor="1层", room="102",
        id_card="330100194801018888",
    )
    TransferRecord.objects.create(
        resident=r, from_zone="自理区", to_zone="介护区", transfer_date="2026-08-01",
        reason="随护理等级由半护转全护，迁入介护区，原因文本超过二十个字以验证截断",
    )
    resp = client.get("/admin/residents/transferrecord/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "介护区" in body and "2号楼" in body
    assert "以验证截断" not in body  # 超长尾部被截掉
    assert body.count("…") >= 1


@pytest.mark.django_db
def test_resident_changelist_has_admission_date(client):
    """老人档案列表含入住日期列——"入院记录"的查询位（需有数据才渲染表头）。"""
    from residents.models import Resident

    superuser = User.objects.create_superuser("lcsup3", "s3@x.com", "123456")
    client.force_login(superuser)
    Resident.objects.create(
        name="档案老人", building="3号楼", floor="2层", room="201",
        id_card="330100194801017777", admission_date="2026-03-12",
    )
    resp = client.get("/admin/residents/resident/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # L10N 中文日期格式（2026年3月12日），非 ISO 串
    assert "入住日期" in body and "3月12日" in body


# ---- 入住记录（AdmissionRecord 代理模型）----

@pytest.mark.django_db
def test_admission_changelist_columns_and_order(client):
    """入住记录表：列头渲染 + 按入住日期倒序（最新在前）。"""
    from residents.models import Resident

    superuser = User.objects.create_superuser("lcsup4", "s4@x.com", "123456")
    client.force_login(superuser)
    Resident.objects.create(name="早入住", building="1号楼", floor="1层", room="101",
                            id_card="330100194801016661", admission_date="2025-01-10")
    Resident.objects.create(name="晚入住", building="1号楼", floor="1层", room="102",
                            id_card="330100194801016662", admission_date="2026-08-01")
    resp = client.get("/admin/residents/admissionrecord/")
    assert resp.status_code == 200
    body = resp.content.decode()
    for col in ("入住日期", "楼栋", "护理等级"):
        assert col in body
    assert body.find("晚入住") < body.find("早入住")  # 倒序
    # 列宽钉（per-model 覆写模板 extrahead）：auto 表格下首列会吞掉全部富余宽度，
    # 日期与姓名间出现大空隙——覆写丢失即此断言失败
    assert "th.column-admission_date" in body


@pytest.mark.django_db
def test_admission_viewonly(client):
    """入住记录 view-only：无新增入口（superuser 亦 403，权限钩子关死）。"""
    superuser = User.objects.create_superuser("lcsup5", "s5@x.com", "123456")
    client.force_login(superuser)
    assert client.get("/admin/residents/admissionrecord/add/").status_code == 403


@pytest.mark.django_db
def test_sidebar_renders_nested_items(client):
    """覆写的 app_list.html 渲染嵌套子项：侧栏出现三个子目录标题。"""
    superuser = User.objects.create_superuser("lcsup6", "s6@x.com", "123456")
    client.force_login(superuser)
    body = client.get("/admin/").content.decode()
    assert "入离院记录" in body
    for title in ("入住记录", "离院记录", "转区记录"):
        assert title in body


def _parent_open_state(body):
    """从渲染 HTML 里取「入离院记录」父项 li 的 navigationOpen 初值。"""
    m = re.search(
        r'<li x-data="\{navigationOpen: (true|false)\}"[^>]*>(?s:.{0,900}?)入离院记录', body
    )
    assert m, "父项 li 的折叠 x-data 未渲染"
    return m.group(1) == "true"


@pytest.mark.django_db
def test_sidebar_nested_collapsible(client):
    """三级目录折叠：默认收起（点击父项切换），停在子页自动展开。"""
    superuser = User.objects.create_superuser("lcsup7", "s7@x.com", "123456")
    client.force_login(superuser)
    home = client.get("/admin/").content.decode()
    # 父项是折叠开关（.prevent 不跳转）；子列表受 navigationOpen 控制
    assert 'x-on:click.prevent="navigationOpen = !navigationOpen"' in home
    assert 'x-show="navigationOpen"' in home
    assert _parent_open_state(home) is False  # 非子页 → 默认收起
    child = client.get("/admin/residents/dischargerecord/").content.decode()
    assert _parent_open_state(child) is True  # 停在离院记录页 → 自动展开


@pytest.mark.django_db
def test_sidebar_taxonomy_pins():
    """全站侧栏规范钉（2026-08-26 整理）：分组口径与层级策略不被悄悄破坏。"""
    from django.conf import settings

    nav = settings.UNFOLD["SIDEBAR"]["navigation"]
    groups = {g["title"]: g for g in nav}
    # 无单项组：原「异常上报」已并入老人照护（IncidentReport 挂 resident）
    assert "异常上报" not in groups
    for g in nav:
        assert len(g["items"]) >= 2, f"分组「{g['title']}」仅 {len(g['items'])} 条，单项组违规"
        # 平铺优先：不含三级父项的平铺条目超 7 条就该收拢
        flat = [i for i in g["items"] if "items" not in i]
        assert len(flat) <= 7, f"「{g['title']}」平铺 {len(flat)} 条超规，应收拢三级父项"
        # 三级父项：2~4 子、必带 link（无 link 会被 UNFOLD sites.py 整枝丢弃）
        for i in g["items"]:
            if "items" in i:
                assert i.get("link"), f"父项「{i['title']}」缺 link，整枝会被丢弃"
                assert 2 <= len(i["items"]) <= 4, f"父项「{i['title']}」子项数违规"
    # 老人照护两大父项在册
    care = {i["title"]: i for i in groups["老人照护"]["items"]}
    assert [s["title"] for s in care["照护记录"]["items"]] == \
        ["护理记录", "健康记录", "用药记录", "作息记录"]
    assert [s["title"] for s in care["评估管理"]["items"]] == \
        ["入住评估", "评估记录", "等级映射表"]
    assert "异常记录" in care  # 并入的照护域安全事件
    # 餐费对账（原「财务月结」/finance/）归膳食组；财务组只留账单域
    meal = {i["title"]: i for i in groups["膳食点餐"]["items"]}
    assert meal["餐费结算"]["items"][1] == \
        {"title": "餐费对账", "icon": "price_check", "link": "/finance/"}
    assert "/finance/" not in {i["link"] for i in groups["财务账单"]["items"]}


def test_login_redirect_pin():
    """登录成功必须落后台首页——Django 默认 /accounts/profile/ 无路由，
    登录后闪 404（录屏镜头会带到，2026-08-26 修）。"""
    from django.conf import settings
    assert settings.LOGIN_REDIRECT_URL == "/admin/"
