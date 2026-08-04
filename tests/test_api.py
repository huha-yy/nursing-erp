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
