"""admin 主页命名钉 — 2026-08-27.

用户发现 /admin/ 主区（Django 默认 app_list）没跟上侧栏目录规范：组名/模型名
还是旧口径（点餐送餐/应收账单/护理日志/库存物品…）。本文件钉住对齐后状态：

1. 主区组名=各 app verbose_name（5 处改名）+ 内置运行时名（urls.py）
2. 主区行名读 verbose_name_plural（auditlog 双写死、内置三模型双属性是坑）
3. 模型 Meta 改名的迁移已生成（9 个 app 的 AlterModelOptions、auth/admin 零漂移）
4. 护理组在主区不见 财务账单/系统管理/审计留痕/后台变更日志（has_module_permission）

断言走 resp.context["app_list"] 而非解析 HTML：免解析、天然只覆盖主区，
规避侧栏同名假阳性（test_sidebar_perms._sidebar 切割坑的教训）。
"""

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import Client


def _app_list(body_owner):
    """登录 superuser 取 /admin/ 主区 app_list（组名 → 模型行名集合）。"""
    client = Client()
    client.force_login(body_owner)
    resp = client.get("/admin/")
    return {a["name"]: {m["name"] for m in a["models"]} for a in resp.context["app_list"]}


# ── 1. superuser 主区全量命名 ──────────────────────────────────

NEW_GROUPS = {
    "老人照护", "人员管理", "院内事务", "异常记录", "膳食点餐",
    "床位管理", "财务账单", "评估管理", "家属服务",
    "审计留痕", "系统管理", "后台变更日志",
}
OLD_GROUPS_GONE = {
    "点餐送餐", "应收账单", "床位台账", "入住评估", "异常上报",
    "认证和授权", "管理", "操作日志",
}

NEW_MODEL_ROWS = {
    "护理记录", "作息记录", "护理等级变更记录",  # residents
    "排班表",                                  # staff
    "楼栋台账", "楼层台账", "房间台账", "床位台账",  # beds
    "价目表",                                   # billing
    "异常记录",                                 # incidents
    "绑定台账",                                 # family
    "库存台账", "审批流程",                       # operations
    "等级映射表",                                # assessments
    "业务操作日志", "后台变更日志",                  # auditlog
    "用户账号", "用户组",                          # auth（运行时）
}
OLD_MODEL_ROWS_GONE = {
    "护理日志", "老人作息", "库存物品", "家属绑定", "审批单",
    "操作日志", "日志记录", "用户", "组",
}


def test_index_groups_renamed(django_db_setup, client, django_user_model):
    owner = django_user_model.objects.create_superuser("nxsup", "s@x.com", "123456")
    groups2rows = _app_list(owner)
    assert set(groups2rows) == NEW_GROUPS, f"主区组名不符：{set(groups2rows) ^ NEW_GROUPS}"
    all_rows = set().union(*groups2rows.values())
    missing = NEW_MODEL_ROWS - all_rows
    assert not missing, f"主区缺新模型行名：{missing}"
    stale = OLD_MODEL_ROWS_GONE & all_rows
    assert not stale, f"主区残留旧模型行名：{stale}"
    # 旧组名彻底退场（set 相等已保证，双保险防 NEW/OLD 集合本身写错）
    assert not (OLD_GROUPS_GONE & set(groups2rows))


# ── 2. 内置运行时名（urls.py hook 丢失即红） ────────────────────


def test_builtin_display_names_patched():
    assert User._meta.verbose_name == "用户账号"
    assert User._meta.verbose_name_plural == "用户账号"
    assert Group._meta.verbose_name == "用户组"
    assert Group._meta.verbose_name_plural == "用户组"
    assert LogEntry._meta.verbose_name == "后台变更日志"
    assert LogEntry._meta.verbose_name_plural == "后台变更日志"
    from django.apps import apps

    assert apps.get_app_config("auth").verbose_name == "系统管理"
    assert apps.get_app_config("admin").verbose_name == "后台变更日志"


# ── 3. 迁移已生成且内置无漂移 ──────────────────────────────────


@pytest.mark.django_db
def test_verbose_name_migrations_recorded():
    """AlterModelOptions 已入库、auth/admin 不因运行时改名误报迁移。"""
    call_command("makemigrations", "--check", "--dry-run")


# ── 4. 护理组主区口径（app_list 按 has_module_permission 过滤） ──


def test_index_nursing_group_scope(client, django_db_setup):
    user = User.objects.create_user("nx_b1", "b@x.com", "123456", is_staff=True)
    user.groups.add(Group.objects.get(name="护理组"))
    client.force_login(user)
    resp = client.get("/admin/")
    groups = {a["name"] for a in resp.context["app_list"]}
    for absent in ("财务账单", "系统管理", "审计留痕", "后台变更日志"):
        assert absent not in groups, f"护理组主区不应见「{absent}」"
    for present in ("老人照护", "膳食点餐", "床位管理", "人员管理", "异常记录"):
        assert present in groups, f"护理组主区应见「{present}」"
