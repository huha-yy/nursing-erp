import pytest
from django.utils import timezone


@pytest.mark.django_db
def test_full_workflow_resident_log_to_incident(client):
    """护理员记录日志 → 发现异常 → 一键上报 完整流程"""
    from residents.models import Resident, NursingLog
    from incidents.models import IncidentReport
    from staff.models import Employee
    from django.contrib.auth.models import User

    # 1. 创建老人档案
    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234",
        diagnosis="高血压, 糖尿病",
    )
    assert Resident.objects.count() == 1

    # 2. 护理员记录护理日志
    log = NursingLog.objects.create(
        resident=resident, log_date="2026-08-04",
        category="vital_signs", detail="血压 165/95，偏高",
    )
    assert NursingLog.objects.count() == 1

    # 3. 护理员发现异常 → 一键上报
    incident = IncidentReport.objects.create(
        resident=resident, category="illness",
        severity="warning",
        description="血压连续偏高，建议调整降压药",
    )
    assert IncidentReport.objects.filter(handled=False).count() == 1

    # 4. API 查询老人日志
    resp = client.get(f"/api/residents/{resident.id}/logs/")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1

    # 5. API 查询未处理异常
    resp = client.get("/api/incidents/?handled=false")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1

    # 6. 标记异常已处理
    incident.handled = True
    incident.handled_at = timezone.now()
    incident.handled_by = "张护士"
    incident.save()
    assert IncidentReport.objects.filter(handled=True).count() == 1


@pytest.mark.django_db
def test_create_superuser_and_employee():
    """验证创建管理员 → 关联员工档案的流程"""
    from django.contrib.auth.models import User
    from staff.models import Employee

    admin_user = User.objects.create_superuser(
        username="admin", email="admin@eldcare.cn", password="admin123"
    )
    emp = Employee.objects.create(
        user=admin_user, name="王建国", dept="综合办",
        phone="13800000001", is_caregiver=False
    )
    assert admin_user.is_superuser
    assert emp.name == "王建国"
    assert emp.dept == "综合办"


@pytest.mark.django_db
def test_building_filter_chain(client):
    """链式查询：1号楼 → 老人 → 护理日志"""
    from residents.models import Resident, NursingLog
    from staff.models import Employee, Schedule
    from django.contrib.auth.models import User

    # 创建不同楼栋的老人
    r1 = Resident.objects.create(name="1号楼老人", building="1号楼", floor="1层",
        room="101", care_level="自理", id_card="330100194801011111")
    r2 = Resident.objects.create(name="2号楼老人", building="2号楼", floor="1层",
        room="101", care_level="全护", id_card="330100194801011112")

    # 1号楼的老人有护理日志
    NursingLog.objects.create(resident=r1, log_date="2026-08-04",
        category="feeding", detail="正常进食")

    # API 查询：只查1号楼的老人
    resp = client.get("/api/residents/?building=1号楼")
    assert len(resp.json()["items"]) == 1

    # API 查询：只查1号楼老人的日志
    resp = client.get(f"/api/residents/{r1.id}/logs/")
    assert len(resp.json()["items"]) == 1

    # API 查询：2号楼老人没有日志
    resp = client.get(f"/api/residents/{r2.id}/logs/")
    assert len(resp.json()["items"]) == 0
