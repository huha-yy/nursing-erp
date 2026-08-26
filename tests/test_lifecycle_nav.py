"""入离院记录导航钉 — 2026-08-26.

用户在床位看板发现二号楼空闲床（杨国华身故离院释放），追问入离院记录为何
没有查询入口：DischargeRecord / TransferRecord 两张 admin 表一直存在，但
UNFOLD 点名制 sidebar 漏配导致导航不可达。本文件钉住三件事，防再漏：

1. sidebar 老人照护组含离院记录 / 转区记录链接
2. 离院记录表页可访问且补列（楼栋 / 原因）生效
3. 老人档案列表含入住日期列（"入院记录"的呈现位——入院即建档挂床，
   无独立事件表，档案列即查询口径）
"""

import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_sidebar_pins_lifecycle_links():
    """UNFOLD 点名制 sidebar：离院/转区记录必须在册（床组曾静默漏配）。"""
    from django.conf import settings

    groups = {g["title"]: g for g in settings.UNFOLD["SIDEBAR"]["navigation"]}
    assert "老人照护" in groups
    links = {i["link"] for i in groups["老人照护"]["items"]}
    assert "/admin/residents/dischargerecord/" in links
    assert "/admin/residents/transferrecord/" in links


@pytest.mark.django_db
def test_discharge_changelist_columns(client):
    """离院记录表：新列（楼栋/原因）渲染 + 行数据可见。"""
    from residents.models import DischargeRecord, Resident

    superuser = User.objects.create_superuser("lcsup1", "s1@x.com", "123456")
    client.force_login(superuser)
    r = Resident.objects.create(
        name="测试老人", building="1号楼", floor="1层", room="101",
        id_card="330100194801019999", admission_date="2026-01-05",
    )
    DischargeRecord.objects.create(
        resident=r, discharge_type="身故", discharge_date="2026-07-20", reason="因病离世",
    )
    resp = client.get("/admin/residents/dischargerecord/")
    assert resp.status_code == 200
    body = resp.content.decode()
    for col in ("离院类型", "离院日期", "楼栋", "原因"):
        assert col in body
    assert "因病离世" in body and "1号楼" in body


@pytest.mark.django_db
def test_transfer_changelist_columns(client):
    """转区记录表：新列（楼栋/原因）渲染 + 长原因截断。"""
    from residents.models import Resident, TransferRecord

    superuser = User.objects.create_superuser("lcsup2", "s2@x.com", "123456")
    client.force_login(superuser)
    r = Resident.objects.create(
        name="转区老人", building="2号楼", floor="1层", room="102",
        id_card="330100194801018888",
    )
    TransferRecord.objects.create(
        resident=r, from_zone="自理区", to_zone="介护区", transfer_date="2026-08-01",
        reason="随护理等级由半护转全护，迁入介护区，原因文本超过二十个字以验证截断",
    )
    resp = client.get("/admin/residents/transferrecord/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "介护区" in body and "2号楼" in body
    assert "以验证截断" not in body  # 超长尾部被截掉
    assert body.count("…") >= 1


@pytest.mark.django_db
def test_resident_changelist_has_admission_date(client):
    """老人档案列表含入住日期列——"入院记录"的查询位（需有数据才渲染表头）。"""
    from residents.models import Resident

    superuser = User.objects.create_superuser("lcsup3", "s3@x.com", "123456")
    client.force_login(superuser)
    Resident.objects.create(
        name="档案老人", building="3号楼", floor="2层", room="201",
        id_card="330100194801017777", admission_date="2026-03-12",
    )
    resp = client.get("/admin/residents/resident/")
    assert resp.status_code == 200
    body = resp.content.decode()
    # L10N 中文日期格式（2026年3月12日），非 ISO 串
    assert "入住日期" in body and "3月12日" in body
