import pytest


@pytest.mark.django_db
def test_create_resident():
    from residents.models import Resident

    resident = Resident.objects.create(
        name="张国栋",
        gender="男",
        age=78,
        id_card="330100194801011234",
        building="1号楼",
        floor="1层",
        room="101",
        care_level="自理",
        diagnosis="高血压, 糖尿病",
    )
    assert resident.name == "张国栋"
    assert resident.care_level == "自理"
    assert str(resident) == "张国栋"


@pytest.mark.django_db
def test_resident_filter_by_building():
    from residents.models import Resident

    Resident.objects.create(
        name="老人A", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011111"
    )
    Resident.objects.create(
        name="老人B", building="2号楼", floor="1层", room="101",
        care_level="全护", id_card="330100194801011112"
    )

    assert Resident.objects.filter(building="1号楼").count() == 1
    assert Resident.objects.filter(care_level="全护").count() == 1


@pytest.mark.django_db
def test_create_nursing_log():
    from residents.models import Resident, NursingLog

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    log = NursingLog.objects.create(
        resident=resident,
        log_date="2026-08-04",
        category="vital_signs",
        detail="血压 135/85，正常",
    )
    assert log.category == "vital_signs"
    assert log.detail == "血压 135/85，正常"


@pytest.mark.django_db
def test_health_record():
    from residents.models import Resident, HealthRecord

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    record = HealthRecord.objects.create(
        resident=resident,
        record_date="2026-08-04",
        blood_pressure="135/85",
        blood_sugar=5.6,
        heart_rate=72,
    )
    assert record.blood_pressure == "135/85"
    assert record.blood_sugar == 5.6


@pytest.mark.django_db
def test_medication_active_filter():
    from residents.models import Resident, MedicationRecord

    resident = Resident.objects.create(
        name="张国栋", building="1号楼", floor="1层", room="101",
        care_level="自理", id_card="330100194801011234"
    )
    MedicationRecord.objects.create(
        resident=resident, medicine_name="氨氯地平", dosage="5mg",
        frequency="qd", start_date="2026-07-01", is_active=True
    )
    MedicationRecord.objects.create(
        resident=resident, medicine_name="二甲双胍", dosage="500mg",
        frequency="bid", start_date="2026-06-01", is_active=False
    )
    assert MedicationRecord.objects.filter(is_active=True).count() == 1
