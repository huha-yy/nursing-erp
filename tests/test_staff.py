import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_create_employee():
    from staff.models import Employee

    user = User.objects.create_user(username="nurse_zhang", password="123456")
    emp = Employee.objects.create(
        user=user,
        name="张护士",
        dept="护理科",
        building="1号楼",
        phone="13800001111",
        is_caregiver=True,
    )
    assert emp.name == "张护士"
    assert emp.dept == "护理科"
    assert str(emp) == "张护士"


@pytest.mark.django_db
def test_schedule_unique_constraint():
    from staff.models import Employee, Schedule
    from django.contrib.auth.models import User
    from django.db.utils import IntegrityError

    user = User.objects.create_user(username="test_staff", password="123456")
    emp = Employee.objects.create(user=user, name="测试员", dept="护理科", phone="13800000000")

    Schedule.objects.create(
        employee=emp, date="2026-08-04", shift="白班", building="1号楼"
    )
    with pytest.raises(IntegrityError):
        Schedule.objects.create(
            employee=emp, date="2026-08-04", shift="白班", building="1号楼"
        )


@pytest.mark.django_db
def test_attendance():
    from staff.models import Employee, Attendance
    from django.contrib.auth.models import User
    from datetime import datetime

    user = User.objects.create_user(username="test_staff2", password="123456")
    emp = Employee.objects.create(user=user, name="测试员2", dept="总务科", phone="13800000001")

    att = Attendance.objects.create(
        employee=emp,
        date="2026-08-04",
        clock_in=datetime(2026, 8, 4, 6, 55),
    )
    assert att.clock_out is None
