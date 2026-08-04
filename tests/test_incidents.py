import pytest


@pytest.mark.django_db
def test_create_incident():
    from residents.models import Resident
    from incidents.models import IncidentReport

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    incident = IncidentReport.objects.create(
        resident=resident,
        category="fall",
        severity="danger",
        description="老人在走廊摔倒，右膝擦伤",
    )
    assert incident.handled is False
    assert incident.severity == "danger"
    assert str(incident).startswith("张国栋") and "摔倒" in str(incident)


@pytest.mark.django_db
def test_incident_filter_unhandled():
    from residents.models import Resident
    from incidents.models import IncidentReport

    resident = Resident.objects.create(
        name="测试老人", building="1号楼", floor="1层", room="102",
        care_level="自理", id_card="330100194801019999"
    )
    IncidentReport.objects.create(
        resident=resident, category="fall", severity="warning",
        description="test1", handled=False
    )
    IncidentReport.objects.create(
        resident=resident, category="illness", severity="info",
        description="test2", handled=True
    )

    assert IncidentReport.objects.filter(handled=False).count() == 1
