import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_list_residents(client):
    from residents.models import Resident

    Resident.objects.create(
        name="老人A", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011111"
    )
    Resident.objects.create(
        name="老人B", building="2号楼", floor="1层", room="101",
        care_level="全护", id_card="330100194801011112"
    )

    resp = client.get("/api/residents/?building=1号楼")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "老人A"


@pytest.mark.django_db
def test_get_resident_detail(client):
    from residents.models import Resident

    r = Resident.objects.create(
        name="老人A", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011111",
        diagnosis="高血压",
    )

    resp = client.get(f"/api/residents/{r.id}/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "老人A"
    assert data["diagnosis"] == "高血压"


@pytest.mark.django_db
def test_list_incidents(client):
    from residents.models import Resident
    from incidents.models import IncidentReport

    r = Resident.objects.create(
        name="测试老人", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801019999"
    )
    IncidentReport.objects.create(
        resident=r, category="fall", severity="danger",
        description="test", handled=False
    )

    resp = client.get("/api/incidents/?handled=false")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["category"] == "fall"


@pytest.mark.django_db
def test_list_schedules(client):
    from staff.models import Employee, Schedule
    from django.contrib.auth.models import User

    user = User.objects.create_user(username="test_staff_api", password="123456")
    emp = Employee.objects.create(user=user, name="测试员", dept="护理科", phone="13800000003")
    Schedule.objects.create(employee=emp, date="2026-08-04", shift="白班", building="1号楼")

    resp = client.get("/api/schedules/?date=2026-08-04")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["shift"] == "白班"


@pytest.mark.django_db
def test_create_nursing_log_via_api(client):
    """Agent 通过 POST /api/nursing-logs/ 写入护理日志"""
    from residents.models import Resident, NursingLog

    r = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )

    resp = client.post("/api/nursing-logs/", data={
        "resident_id": r.id,
        "category": "vital_signs",
        "detail": "血压 135/85，正常",
        "staff_name": "李芳",
    }, content_type="application/json")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert data["id"] > 0

    # Verify it was actually created
    log = NursingLog.objects.get(id=data["id"])
    assert log.detail == "血压 135/85，正常"
    assert log.resident_id == r.id


@pytest.mark.django_db
def test_create_incident_via_api(client):
    """Agent 通过 POST /api/incidents/ 上报异常"""
    from residents.models import Resident
    from incidents.models import IncidentReport

    r = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )

    resp = client.post("/api/incidents/", data={
        "resident_id": r.id,
        "category": "fall",
        "severity": "danger",
        "description": "老人在走廊摔倒，右膝擦伤",
    }, content_type="application/json")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"

    # Verify
    incident = IncidentReport.objects.get(id=data["id"])
    assert incident.severity == "danger"
    assert incident.handled is False


@pytest.mark.django_db
def test_create_health_record_via_api(client):
    """Agent 通过 POST /api/health-records/ 写入健康数据"""
    from residents.models import Resident, HealthRecord

    r = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )

    resp = client.post("/api/health-records/", data={
        "resident_id": r.id,
        "blood_pressure": "135/85",
        "blood_sugar": 5.6,
        "heart_rate": 72,
    }, content_type="application/json")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"

    hr = HealthRecord.objects.get(id=data["id"])
    assert hr.blood_pressure == "135/85"


@pytest.mark.django_db
def test_handle_incident_marks_and_stamps(client):
    """POST /api/incidents/{id}/handle/：置 handled + 记处理人/时间（2026-08-25）"""
    import json

    from residents.models import Resident
    from incidents.models import IncidentReport

    r = Resident.objects.create(
        name="测试老人", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801019999"
    )
    inc = IncidentReport.objects.create(
        resident=r, category="wander", severity="warning", description="在楼道徘徊"
    )

    resp = client.post(
        f"/api/incidents/{inc.id}/handle/",
        data=json.dumps({"operator": "王建国"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "handled"

    inc.refresh_from_db()
    assert inc.handled is True
    assert inc.handled_by == "王建国"
    assert inc.handled_at is not None

    # 列表输出带处理人/时间（告警详情面板用）
    item = client.get("/api/incidents/").json()["items"][0]
    assert item["handled_by"] == "王建国"
    assert item["handled_at"]


@pytest.mark.django_db
def test_handle_incident_idempotent_and_404(client):
    """重复 handle 不改写首次时间；未知 id 404"""
    import json

    from residents.models import Resident
    from incidents.models import IncidentReport

    r = Resident.objects.create(
        name="测试老人2", building="1号楼", floor="1层", room="102",
        care_level="自理", id_card="330100194801018888"
    )
    inc = IncidentReport.objects.create(resident=r, category="fall", severity="danger")

    client.post(f"/api/incidents/{inc.id}/handle/",
                data=json.dumps({"operator": "第一人"}),
                content_type="application/json")
    first_at = IncidentReport.objects.get(id=inc.id).handled_at

    resp = client.post(f"/api/incidents/{inc.id}/handle/",
                       data=json.dumps({"operator": "第二人"}),
                       content_type="application/json")
    assert resp.json()["status"] == "already_handled"
    inc.refresh_from_db()
    assert inc.handled_by == "第一人"  # 首次署名不被覆盖
    assert inc.handled_at == first_at

    assert client.post("/api/incidents/99999/handle/",
                       data="{}", content_type="application/json").status_code == 404
