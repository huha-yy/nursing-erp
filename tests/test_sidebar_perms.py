"""侧栏按用户组权限过滤钉 — 2026-08-27.

用户以不同演示账号登录发现侧栏全员全量（点进去才 403）。本文件钉住：

1. settings 导航树结构：除 chat 外链外每项挂 permission（callable）；
   三级父项 codename 集合 == 子项并集（防"子可见父隐藏=整枝不可达"漂移）；
   每项仍带 link（UNFOLD sites.py 丢弃无 link 项）
2. nav_perms 回调单元：匿名 False / superuser True / 裸 staff 全 False
3. nav_deep_visible filter：浅层命中 / 嵌套命中 / 全 False
4. 六用户组 + superuser 的 /admin/ 侧栏渲染精确预期
   （组数、组标题集合、关键入口在/不在——从 GROUP_PERMS 严格推导）

轻量页（看板/OCR/快速记录）后端仅 @staff_required 不分组，permission
给的是导航层业务归属（用户拍板 2026-08-27），直链仍开放。
"""

import pytest
from django.contrib.auth.models import Group, User
from django.test import RequestFactory

from nursing_erp import nav_perms
from residents.templatetags.residents_tags import nav_deep_visible

# 六组在 /admin/ 侧栏应见的组标题（AI 院长助手因 chat 外链无 permission 恒可见）
GROUPS_SEE = {
    "院办管理组": {
        "AI 院长助手", "老人照护", "床位管理", "膳食点餐", "财务账单",
        "人员管理", "院内事务", "家属服务", "审计留痕", "系统管理",
    },
    "护理组": {"AI 院长助手", "老人照护", "床位管理", "膳食点餐", "人员管理"},
    "医务组": {"AI 院长助手", "老人照护", "床位管理"},
    "财务组": {"AI 院长助手", "老人照护", "床位管理", "膳食点餐", "财务账单"},
    "总务组": {"AI 院长助手", "床位管理", "院内事务"},
    "安保组": {"AI 院长助手", "老人照护", "床位管理"},
}


def _sidebar(client, username, group_name=None, superuser=False):
    """造用户挂组 → 登录 → 取 /admin/ 侧栏片段。

    必须切侧栏片段：主区 app_list_default 也渲染模型中文名（「报修工单」
    「老人照护」），缺席断言不切割必假阳性。
    """
    user = User.objects.create_user(
        username, "t@example.com", "123456", is_staff=True, is_superuser=superuser
    )
    if group_name:
        user.groups.add(Group.objects.get(name=group_name))
    client.force_login(user)
    body = client.get("/admin/").content.decode()
    return body.split('id="nav-sidebar-inner"', 1)[1].split('<div id="main"', 1)[0]


# ── 1. 结构钉（无 DB） ──────────────────────────────────────────


def _walk_items():
    """只遍历导航项（二级 item 与三级 sub），不含组级（组级不配 permission）。"""
    from django.conf import settings

    for group in settings.UNFOLD["SIDEBAR"]["navigation"]:
        for item in group["items"]:
            yield item
            yield from item.get("items") or []


def test_nav_items_carry_permission_except_chat():
    chats = []
    for node in _walk_items():
        if node.get("link", "").startswith("https://"):
            chats.append(node["title"])
            continue
        assert callable(node.get("permission")), \
            f"「{node['title']}」缺 permission（callable）"
    assert chats == ["打开 AI Chat"]  # 唯一免检外链


def test_nav_parent_perm_is_union_of_children():
    """父项 any_perm 并集 == 子项并集，防加子项忘并父项（整枝不可达）。"""
    from django.conf import settings

    for group in settings.UNFOLD["SIDEBAR"]["navigation"]:
        for item in group["items"]:
            subs = item.get("items")
            if not subs:
                continue
            parent = set(item["permission"].nav_perms)
            union = set()
            for s in subs:
                union |= set(s["permission"].nav_perms)
            assert parent == union, \
                f"父项「{item['title']}」perm != 子项并集：{parent} vs {union}"


def test_nav_items_keep_link():
    for node in _walk_items():
        assert node.get("link"), f"「{node['title']}」缺 link，会被 sites.py 丢弃"


# ── 2. nav_perms 单元 ──────────────────────────────────────────


def _req():
    return RequestFactory().get("/")  # user 由各用例自行挂


def test_nav_perms_anonymous_all_false():
    from django.contrib.auth.models import AnonymousUser

    r = _req()
    r.user = AnonymousUser()
    for name in ("resident", "kitchen_board", "quick_log", "user_admin"):
        assert getattr(nav_perms, name)(r) is False


def test_nav_perms_superuser_all_true():
    r = _req()
    r.user = User(is_superuser=True)  # 不落库；has_perm 对超管恒真
    for name in ("resident", "kitchen_board", "quick_log", "user_admin",
                 "care_records", "lifecycle_records"):
        assert getattr(nav_perms, name)(r) is True


@pytest.mark.django_db
def test_nav_perms_bare_staff_all_false():
    """无组裸 staff（is_staff 无组权限）：除 chat 外全部不可见。

    须落库——has_perm 会查 user_permissions m2m，未保存用户无 id 直接炸
    （superuser 因短路先判 is_superuser 才不炸）。
    """
    r = _req()
    r.user = User.objects.create_user("t_bare", "b@x.com", "123456", is_staff=True)
    # any_perm 是工厂不是回调（调用会返回闭包），排除在遍历外
    checked = [n for n in dir(nav_perms) if not n.startswith("_") and n != "any_perm"]
    for name in checked:
        assert getattr(nav_perms, name)(r) is False


# ── 3. nav_deep_visible filter ─────────────────────────────────


def test_nav_deep_visible_cases():
    assert nav_deep_visible([{"has_permission": True}]) is True  # 浅层
    assert nav_deep_visible([{"items": [{"has_permission": True}]}]) is True  # 嵌套
    assert nav_deep_visible([{"has_permission": False},
                             {"items": [{"has_permission": False}]}]) is False


# ── 4. 六组 + superuser 渲染预期（django_db：0006/0009 迁移已种组） ──


def _h2_titles(sidebar):
    import re

    # h2 内嵌 badge/chevron 标签，title 到下一个 < 为止（非整段 </h2>）
    return {m for m in re.findall(r"<h2[^>]*>\s*([^<]+?)\s*<", sidebar)}


@pytest.mark.django_db
@pytest.mark.parametrize("group_name", list(GROUPS_SEE))
def test_sidebar_group_visibility(client, group_name):
    sidebar = _sidebar(client, f"t_{group_name}", group_name)
    assert _h2_titles(sidebar) == GROUPS_SEE[group_name], \
        f"{group_name} 侧栏组集合不符"


@pytest.mark.django_db
def test_sidebar_superuser_full(client):
    sidebar = _sidebar(client, "t_root", superuser=True)
    assert _h2_titles(sidebar) == GROUPS_SEE["院办管理组"]  # 全 10 组


@pytest.mark.django_db
def test_sidebar_nursing_group_details(client):
    """护理组（b1_liu 同组）关键入口抽查。"""
    sb = _sidebar(client, "t_nurse", "护理组")
    for present in ("快速记录", "菜单 OCR", "点餐订单", "床位看板", "排班表",
                    "照护记录", "入离院记录", "异常记录"):
        assert present in sb, f"护理组应见「{present}」"
    for absent in ("改退餐记录", "餐费月结", "餐费对账", "员工档案", "绩效考核",
                   "应收月账单", "库存台账"):
        assert absent not in sb, f"护理组不应见「{absent}」"


@pytest.mark.django_db
def test_sidebar_medical_group_details(client):
    """医务组：入离院整枝隐藏、无食堂看板/排班。"""
    sb = _sidebar(client, "t_med", "医务组")
    for present in ("快速记录", "照护记录", "评估管理", "异常记录", "床位看板"):
        assert present in sb, f"医务组应见「{present}」"
    for absent in ("入离院记录", "入住记录", "离院记录", "转区记录",
                   "食堂看板", "排班表"):
        assert absent not in sb, f"医务组不应见「{absent}」"


@pytest.mark.django_db
def test_sidebar_finance_group_details(client):
    """财务组（fin_sun 同组）：照护组只剩老人档案，床位组只剩楼栋台账。"""
    sb = _sidebar(client, "t_fin", "财务组")
    for present in ("老人档案", "楼栋台账", "食堂看板", "餐费对账", "餐费月结",
                    "改退餐记录", "点餐订单", "周选点餐", "点餐 OCR", "账单看板"):
        assert present in sb, f"财务组应见「{present}」"
    for absent in ("照护记录", "异常记录", "楼层台账", "床位看板", "菜品库",
                   "周菜单", "菜单 OCR", "快速记录"):
        assert absent not in sb, f"财务组不应见「{absent}」"


@pytest.mark.django_db
def test_sidebar_logistics_group_details(client):
    """总务组（logi_chen 同组）：床位+院内事务+AI。"""
    sb = _sidebar(client, "t_logi", "总务组")
    for present in ("床位看板", "库存台账", "入库记录", "领用记录", "报修工单",
                    "卫生巡检", "审批流程"):
        assert present in sb, f"总务组应见「{present}」"
    for absent in ("老人档案", "食堂看板", "快速记录", "员工档案"):
        assert absent not in sb, f"总务组不应见「{absent}」"


@pytest.mark.django_db
def test_sidebar_security_group_details(client):
    """安保组：照护组只剩 老人档案+异常记录。"""
    sb = _sidebar(client, "t_sec", "安保组")
    for present in ("老人档案", "异常记录", "床位看板", "床位台账"):
        assert present in sb, f"安保组应见「{present}」"
    for absent in ("照护记录", "评估管理", "快速记录", "食堂看板", "排班表"):
        assert absent not in sb, f"安保组不应见「{absent}」"
