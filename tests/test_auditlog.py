"""审计留痕（auditlog app）测试 — 2026-08-25。

两层采集的核心契约：
1. 埋点层：关键业务动作记人话行（action/target/detail），并抑制同请求
   的兜底行——一事一行；
2. 兜底层：未埋点的 /api/* 写请求自动留痕（含失败写，status_code 落账），
   GET 无痕；/api/family/auth/（带密码）永不记；
3. 身份解析：api-key→AI / FamilyMember 实例→家属 / 员工 session→员工名 /
   operator 转发署名经员工台账核对（查到=员工，查不到=AI 渠道署名）；
4. 查看侧：UNFOLD 点名制 sidebar 审计留痕组在册、admin 只读。
"""

import itertools

import pytest
from django.contrib.auth.models import User
from django.test import Client

from auditlog.models import OperationLog

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _erp_key(settings):
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


def _employee(name, building=""):
    from staff.models import Employee

    user = User.objects.create_user(username=f"emp{_ids.__next__()}", password="x")
    return Employee.objects.create(
        user=user, name=name, dept="护理科", building=building, phone="1"
    )


def _machine_client():
    """ERP_API_KEY 机器调用方（dl-control 形态）——conftest client 的本模块版。"""
    return Client(HTTP_X_API_KEY="test-api-key")


# ---- 1. 埋点层：人话行 + 兜底抑制 ----


@pytest.mark.django_db
def test_instrumented_write_one_semantic_row(client):
    """埋点端点（异常上报）：恰好 1 行、人话 action/target、AI 身份、target_id 落账。"""
    r = _resident()
    resp = client.post("/api/incidents/", data={
        "resident_id": r.id, "category": "fall", "severity": "warning",
        "description": "走廊摔倒",
    }, content_type="application/json")
    assert resp.status_code == 200

    logs = OperationLog.objects.all()
    assert logs.count() == 1  # 埋点行在，兜底行被抑制
    row = logs.get()
    assert row.action == "异常上报"
    assert r.name in row.target and "摔倒" in row.target  # 老人 + 类别人话
    assert "[紧急]" in row.detail and "走廊摔倒" in row.detail  # warning→紧急
    assert row.target_model == "incidents.IncidentReport"
    assert row.target_id == str(resp.json()["id"])
    assert row.actor_type == OperationLog.Actor.AI
    assert row.actor_name == "AI 助手"
    assert row.status_code == 200
    assert row.user is None


@pytest.mark.django_db
def test_fallback_catches_uninstrumented_write(client):
    """未埋点端点（健康记录）走兜底：路径表标签、无 target/detail、身份照常解析。"""
    r = _resident()
    resp = client.post("/api/health-records/", data={
        "resident_id": r.id, "blood_pressure": "120/80",
    }, content_type="application/json")
    assert resp.status_code == 200

    logs = OperationLog.objects.all()
    assert logs.count() == 1
    row = logs.get()
    assert row.action == "健康记录录入"  # middleware 路径表的人话标签
    assert row.target == "" and row.detail == ""  # 兜底不落请求体
    assert row.path == "/api/health-records/"
    assert row.actor_type == OperationLog.Actor.AI
    assert row.status_code == 200


@pytest.mark.django_db
def test_failed_write_still_traced(client):
    """失败的写也留痕（404）：埋点未执行 → 兜底行记下状态码——审计关心失败。"""
    resp = client.post("/api/incidents/", data={
        "resident_id": 99999, "category": "fall",
    }, content_type="application/json")
    assert resp.status_code == 404

    row = OperationLog.objects.get()
    assert row.action == "异常上报接口"
    assert row.status_code == 404


@pytest.mark.django_db
def test_get_requests_leave_no_trace(client):
    """GET 无痕：读操作不是审计对象。"""
    _resident()
    assert client.get("/api/incidents/").status_code == 200
    assert client.get("/api/residents/").status_code == 200
    assert OperationLog.objects.count() == 0


@pytest.mark.django_db
def test_family_auth_endpoint_never_logged(client):
    """/api/family/auth/ 带密码：路径前缀命中跳过表，401 也零落账（红线）。"""
    resp = client.post("/api/family/auth/", data={
        "phone": "13800000000", "password": "wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert OperationLog.objects.count() == 0


# ---- 2. 身份解析 ----


@pytest.mark.django_db
def test_staff_session_write_logged_as_staff():
    """员工 session 写护理日志：埋点行 + 员工真名 + user 外键落账。"""
    emp = _employee("李护理员")
    r = _resident()
    c = Client()
    c.force_login(emp.user)

    resp = c.post("/api/nursing-logs/", data={
        "resident_id": r.id, "category": "feeding", "detail": "午餐进食一半",
    }, content_type="application/json")
    assert resp.status_code == 200

    row = OperationLog.objects.get()
    assert row.action == "护理日志录入"
    assert row.actor_type == OperationLog.Actor.STAFF
    assert row.actor_name == "李护理员"
    assert row.user == emp.user


@pytest.mark.django_db
def test_family_token_write_logged_as_family():
    """家属令牌（X-Family-Token 机器路径）退餐：记家属身份 + 家属名。"""
    from family.models import FamilyMember
    from meals.models import MealOrder

    r = _resident()
    fm = FamilyMember.objects.create(
        user=User.objects.create_user(username=f"1380000{_ids.__next__():04d}",
                                      password="x"),
        name="王丽华", phone="13800001111",
    )
    fm.bindings.create(resident=r, relation="子女")
    order = MealOrder.objects.create(resident=r, date="2026-08-26", meal_type="午餐")

    c = Client(HTTP_X_API_KEY="test-api-key", HTTP_X_FAMILY_TOKEN=fm.token)
    resp = c.post(f"/api/family/meal-orders/{order.id}/cancel/",
                  data={"reason": "不吃辣"}, content_type="application/json")
    assert resp.status_code == 200

    row = OperationLog.objects.get()
    assert row.action == "家属退餐"
    assert row.actor_type == OperationLog.Actor.FAMILY
    assert row.actor_name == "王丽华"
    assert r.name in row.target and "不吃辣" in row.detail


@pytest.mark.django_db
def test_operator_override_resolved_via_employee_ledger(client):
    """handle 转发署名（dl-control operator）：台账查到→员工；查不到→AI 渠道署名。"""
    from incidents.models import IncidentReport

    _employee("陈组长")  # 台账里有的名字
    r = _resident()
    inc1 = IncidentReport.objects.create(resident=r, category="fall",
                                         severity="warning", description="x")
    inc2 = IncidentReport.objects.create(resident=r, category="mood",
                                         severity="info", description="y")

    resp = client.post(f"/api/incidents/{inc1.id}/handle/",
                       data={"operator": "陈组长"}, content_type="application/json")
    assert resp.status_code == 200
    resp = client.post(f"/api/incidents/{inc2.id}/handle/",
                       data={"operator": "外部署名"}, content_type="application/json")
    assert resp.status_code == 200

    rows = {row.target_id: row for row in OperationLog.objects.all()}
    assert rows[str(inc1.id)].actor_type == OperationLog.Actor.STAFF
    assert rows[str(inc1.id)].actor_name == "陈组长"
    assert rows[str(inc2.id)].actor_type == OperationLog.Actor.AI  # 不冒认员工
    assert rows[str(inc2.id)].actor_name == "外部署名"


# ---- 3. 查看侧 ----


@pytest.mark.django_db
def test_sidebar_pins_audit_group():
    """UNFOLD 点名制 sidebar：审计留痕组必须在册（床组曾静默漏配的前车之鉴）。"""
    from django.conf import settings

    groups = {g["title"]: g for g in settings.UNFOLD["SIDEBAR"]["navigation"]}
    assert "审计留痕" in groups
    links = {i["link"] for i in groups["审计留痕"]["items"]}
    assert links == {"/admin/auditlog/operationlog/", "/admin/admin/logentry/"}


@pytest.mark.django_db
def test_operationlog_admin_readonly():
    """审计日志 admin 只读：增删改全禁（保完整性）。"""
    from django.contrib import admin as dj_admin

    from auditlog.admin import DjangoLogEntryAdmin, OperationLogAdmin

    assert issubclass(OperationLogAdmin, dj_admin.ModelAdmin)
    op_admin = OperationLogAdmin(OperationLog, dj_admin.site)
    assert not op_admin.has_add_permission(None)
    assert not op_admin.has_change_permission(None)
    assert not op_admin.has_delete_permission(None)

    le_admin = DjangoLogEntryAdmin.__new__(DjangoLogEntryAdmin)
    assert not le_admin.has_add_permission(None)
    assert not le_admin.has_delete_permission(None)


@pytest.mark.django_db
def test_admin_pages_render_for_superuser(client):
    """HTTP 级渲染（超管）：两张审计页 200，操作日志含筛选/导出（import_export）。"""
    from django.contrib.admin.models import LogEntry

    superuser = User.objects.create_superuser("rootsup_audit", "a@x.com", "123456")
    client.force_login(superuser)
    r = _resident()
    OperationLog.objects.create(
        actor_type=OperationLog.Actor.AI, actor_name="AI 助手",
        action="异常上报", target=f"{r.name} · 摔倒", method="POST",
        path="/api/incidents/", status_code=200,
    )
    LogEntry.objects.create(
        user_id=superuser.id, object_id="1", object_repr="测试",
        action_flag=2, change_message="改了一条",
    )

    resp = client.get("/admin/auditlog/operationlog/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "AI 助手" in body and "异常上报" in body
    assert "actor_type" in body          # 筛选器
    assert "Export" in body or "导出" in body or "export" in body  # import_export 动作

    resp = client.get("/admin/admin/logentry/")
    assert resp.status_code == 200
    assert "改了一条" in resp.content.decode()
