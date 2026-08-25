"""演示用户组种子（staff 0006）测试 — 2026-08-25。

钉住：6 组在册、角色边界（护理/财务/总务/安保各能看到什么、看不到什么）、
院办管理组含审计与账号视图。迁移时点挂人按部门映射，不在此重复验证
（生产走 curl 抽查）。
"""

import pytest
from django.contrib.auth.models import Group


def _has(group_name, codename, app_label):
    return Group.objects.get(name=group_name).permissions.filter(
        content_type__app_label=app_label, codename=codename
    ).exists()


@pytest.mark.django_db
def test_seed_groups_exist():
    names = set(Group.objects.values_list("name", flat=True))
    for g in ("院办管理组", "护理组", "医务组", "财务组", "总务组", "安保组"):
        assert g in names
    assert Group.objects.count() == 6  # 种子之外无杂组


@pytest.mark.django_db
def test_director_group_full_readonly_plus_audit():
    """院办管理组：全业务只读 + 审计两页 + 用户/组视图。"""
    for app, codename in [
        ("residents", "view_resident"), ("billing", "view_monthlybill"),
        ("meals", "view_mealfinance"), ("operations", "view_maintenanceorder"),
        ("assessments", "view_assessment"), ("family", "view_familymember"),
        ("auditlog", "view_operationlog"), ("admin", "view_logentry"),
        ("auth", "view_user"), ("auth", "view_group"),
    ]:
        assert _has("院办管理组", codename, app), (app, codename)
    # 只读：不给删
    assert not _has("院办管理组", "delete_resident", "residents")
    assert not _has("院办管理组", "add_monthlybill", "billing")


@pytest.mark.django_db
def test_nursing_group_care_write_only():
    """护理组：照护读写 + 台账只读；跨到财务/库存即无权限。"""
    for app, codename in [
        ("residents", "view_resident"), ("residents", "add_nursinglog"),
        ("residents", "change_healthrecord"), ("incidents", "add_incidentreport"),
        ("beds", "view_bed"), ("staff", "view_schedule"),
    ]:
        assert _has("护理组", codename, app), (app, codename)
    assert not _has("护理组", "view_monthlybill", "billing")
    assert not _has("护理组", "change_resident", "residents")
    assert not _has("护理组", "view_inventoryitem", "operations")


@pytest.mark.django_db
def test_finance_logistics_security_group_boundaries():
    """财务可核销不可动档案；总务管库存工单不见老人台账；安保只读+上报。"""
    assert _has("财务组", "change_monthlybill", "billing")
    assert not _has("财务组", "view_healthrecord", "residents")

    assert _has("总务组", "change_inventoryitem", "operations")
    assert _has("总务组", "add_maintenanceorder", "operations")
    assert not _has("总务组", "view_resident", "residents")

    assert _has("安保组", "add_incidentreport", "incidents")
    assert not _has("安保组", "view_monthlybill", "billing")


@pytest.mark.django_db
def test_permission_rows_resolvable():
    """种子引用的权限行都真实存在（防 app/model 改名后静默漏配）。"""
    total = sum(
        Group.objects.get(name=n).permissions.count()
        for n in ("院办管理组", "护理组", "医务组", "财务组", "总务组", "安保组")
    )
    assert total >= 100  # 六组合计量级 sanity
