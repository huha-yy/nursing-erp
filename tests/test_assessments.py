"""入住评估→定级（assessments）测试 — 阶段二收尾，2026-08-24。

分层（仿 test_billing.py）：
1. 模型层 8：种子钉（国标 26 项/满分 190/映射 5 行无失智）/ 分段全边界 /
   映射缺行 fail-loud / 建单算分（归一化→等级→建议）/ 建单校验原子零残留 /
   confirm 闭环（档案翻转+关联变更行）/ 改判失智 / from==to 留痕+重复确认拒
2. 服务层 2：review_lists 三态分类+无床排除 / 目录改动不腐蚀历史单
3. API 4：建单+详情契约 / 列表过滤+X-Building scope / confirm 守卫 /
   confirm 校验（坏档位、改判无原因）
4. 页面 3：匿名跳转+登录渲染 / POST 建单+定级（session 员工名）/ 生命周期事件
5. admin 1：楼栋过滤 + confirmed 冻结 + action 逐单定级

核心不变式：定级确认 = 原子（评估单落定 + Resident.care_level 翻转 +
自动生成关联 CareLevelChange），from==to 也留痕——评估单是等级的监管依据。
"""

import itertools
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import User

_ids = itertools.count(1)


def _resident(**kw):
    from residents.models import Resident

    kw.setdefault("name", "测试老人")
    kw.setdefault("building", "1号楼")
    kw.setdefault("floor", "1层")
    kw.setdefault("room", "101")
    kw.setdefault("care_level", "自理")
    kw.setdefault("id_card", f"33010019480101000{_ids.__next__():03d}")
    return Resident.objects.create(**kw)


def _bed(building="1号楼", floor="1层", room="101", number="1"):
    from beds.models import Bed, Building, Floor, Room

    b, _ = Building.objects.get_or_create(name=building)
    f, _ = Floor.objects.get_or_create(building=b, name=floor)
    r, _ = Room.objects.get_or_create(floor=f, number=room)
    bed, _ = Bed.objects.get_or_create(room=r, number=number)
    return bed


def _employee(name, building=""):
    user = User.objects.create_user(username=f"emp{_ids.__next__()}", password="x")
    from staff.models import Employee

    return Employee.objects.create(
        user=user, name=name, dept="护理部", building=building, phone="1"
    )


def _items():
    from assessments.models import AssessmentItem

    return list(AssessmentItem.objects.filter(is_active=True))


def _scores(target: int) -> dict[int, int]:
    """按目标总分（0-100）等比例生成 26 项——演示脚本 synth_scores 同款。

    派生值有舍入（Python 银行家舍入），关键总分在用例里附算式。
    """
    return {i.id: round(i.max_score * target / 100) for i in _items()}


def _assess(resident, target=55, d=None, a1="李医生", a2="王护士"):
    from assessments.services import create_assessment

    return create_assessment(resident, d or date(2026, 8, 1), a1, a2, _scores(target))


# ---- 1. 模型层 ----


@pytest.mark.django_db
def test_seed_default_values():
    """种子迁移钉：国标 26 项、维度计数 8-4-9-5、原始满分 190、映射 5 行无失智"""
    from collections import Counter

    from assessments.models import AssessmentItem, GradeLevelMap

    items = list(AssessmentItem.objects.all())
    assert len(items) == 26
    assert Counter(i.dimension for i in items) == {
        "自理能力": 8, "基础运动能力": 4, "精神状态": 9, "感知觉与社会参与": 5,
    }
    assert sum(i.max_score for i in items) == 190  # 12×10 + 14×5
    assert {i.max_score for i in items} == {10, 5}

    maps = {m.grade: m.care_level for m in GradeLevelMap.objects.all()}
    assert maps == {0: "自理", 1: "自理", 2: "半护", 3: "全护", 4: "全护"}
    assert "失智" not in maps.values()  # 失智只能定级改判（reason 必填）


@pytest.mark.django_db
def test_grade_bands_all_boundaries():
    """国标分段常量：全边界 + 越界 fail-loud"""
    from assessments.models import Assessment

    for total, grade in [
        (0, 0), (20, 0), (21, 1), (45, 1), (46, 2),
        (65, 2), (66, 3), (90, 3), (91, 4), (100, 4),
    ]:
        assert Assessment.grade_for_score(total) == grade
    for bad in (101, -1):
        with pytest.raises(ValueError, match="越界"):
            Assessment.grade_for_score(bad)


@pytest.mark.django_db
def test_grade_map_missing_fail_loud():
    """映射缺行 → GradeMapMissing；建单路径（recalculate）同步暴露——
    数据录入时就暴露配置缺失，而非等定级（仿 FeeRule 出账时机）"""
    from assessments.models import GradeLevelMap, GradeMapMissing

    GradeLevelMap.objects.filter(grade=2).delete()
    with pytest.raises(GradeMapMissing, match="等级映射表缺行"):
        GradeLevelMap.get_level_for_grade(2)

    with pytest.raises(GradeMapMissing):
        _assess(_resident(), target=55)  # 55 → 2级 → 查映射
    from assessments.models import Assessment

    assert Assessment.objects.count() == 0  # 同事务回滚，零残留


@pytest.mark.django_db
def test_create_assessment_scoring():
    """建单算分：归一化总分 → 等级 → 建议档（映射种子）"""
    a100 = _assess(_resident(), target=100)
    assert (a100.total_score, a100.grade, a100.suggested_level) == (100, 4, "全护")
    assert a100.scores.count() == 26

    # 55：12×round(5.5)+14×round(2.75)=72+42=114 → round(114×100/190)=60
    a55 = _assess(_resident(), target=55)
    assert (a55.total_score, a55.grade, a55.suggested_level) == (60, 2, "半护")

    # 10：10分项 round(1)=1、5分项 round(0.5)=0（银行家舍入）→ 12 → round(1200/190)=6
    a10 = _assess(_resident(), target=10)
    assert (a10.total_score, a10.grade, a10.suggested_level) == (6, 0, "自理")

    a0 = _assess(_resident(), target=0)
    assert (a0.total_score, a0.grade, a0.suggested_level) == (0, 0, "自理")


@pytest.mark.django_db
def test_create_validation_atomic():
    """建单校验 fail-loud（缺项/多项/越界/非整数/布尔/空评估员/空目录）+ 原子零残留"""
    from assessments.models import Assessment, AssessmentItem, AssessmentScore
    from assessments.services import create_assessment

    r = _resident()
    full = _scores(50)
    first = next(iter(full))
    d = date(2026, 8, 1)
    cases = [
        ({k: v for k, v in list(full.items())[:25]}, "李医生", "王护士", "缺 1 项"),
        ({**full, 99999: 0}, "李医生", "王护士", "多 1 项"),
        ({**full, first: 11}, "李医生", "王护士", "超出 0-10"),
        ({**full, first: "5"}, "李医生", "王护士", "须为整数"),
        ({**full, first: True}, "李医生", "王护士", "须为整数"),  # bool 是 int 子类，显式拒
        (full, "", "王护士", "评估员"),
        (full, "  ", "王护士", "评估员"),
    ]
    for scores, a1, a2, msg in cases:
        with pytest.raises(ValueError, match=msg):
            create_assessment(r, d, a1, a2, scores)

    AssessmentItem.objects.update(is_active=False)
    with pytest.raises(ValueError, match="目录为空"):
        create_assessment(r, d, "李医生", "王护士", full)

    assert Assessment.objects.count() == 0
    assert AssessmentScore.objects.count() == 0


@pytest.mark.django_db
def test_confirm_updates_resident_and_log():
    """confirm 闭环：评估单落定 + care_level 翻转 + 关联变更行（change_date=评估日）"""
    from assessments.models import Assessment
    from residents.models import CareLevelChange

    r = _resident(care_level="自理")
    a = _assess(r, target=55, d=date(2026, 7, 1))
    a.confirm(operator="刘主任")

    r.refresh_from_db()
    assert r.care_level == "半护"
    a.refresh_from_db()
    assert a.status == Assessment.Status.CONFIRMED
    assert a.final_level == "半护" and a.confirmed_by == "刘主任" and a.confirmed_at

    chg = CareLevelChange.objects.get(assessment=a)
    assert (chg.from_level, chg.to_level) == ("自理", "半护")
    assert chg.change_date == date(2026, 7, 1)  # = assess_date：补录与月度出账对齐
    assert "总分 60" in chg.reason and "建议 半护" in chg.reason
    assert chg.changed_by == "刘主任"


@pytest.mark.django_db
def test_confirm_override_to_dementia():
    """改判失智：无 reason 拒（且全回滚）；有 reason 成——失智的唯一进入路径"""
    from assessments.models import Assessment
    from residents.models import CareLevelChange

    r = _resident(care_level="半护")
    a = _assess(r, target=55)

    with pytest.raises(ValueError, match="原因"):
        a.confirm(operator="刘主任", final_level="失智")
    r.refresh_from_db()
    assert r.care_level == "半护"  # 原子回滚，档案不动
    a.refresh_from_db()
    assert a.status == Assessment.Status.DRAFT
    assert CareLevelChange.objects.count() == 0

    a.confirm(operator="刘主任", final_level="失智", reason="认知量表提示痴呆")
    r.refresh_from_db()
    assert r.care_level == "失智"
    chg = CareLevelChange.objects.get(assessment=a)
    assert chg.to_level == "失智" and "认知量表提示痴呆" in chg.reason


@pytest.mark.django_db
def test_confirm_same_level_logs_and_double_raises():
    """from==to 也留痕（评估单是监管依据，不是差量信号）+ 重复确认拒"""
    from residents.models import CareLevelChange

    r = _resident(care_level="半护")
    a = _assess(r, target=55)  # 建议 半护 == 现档
    a.confirm(operator="王院长")

    r.refresh_from_db()
    assert r.care_level == "半护"  # 值没变
    assert CareLevelChange.objects.filter(assessment=a).count() == 1  # 但留痕

    with pytest.raises(ValueError, match="不可重复"):
        a.confirm(operator="王院长", final_level="全护")
    assert CareLevelChange.objects.filter(assessment=a).count() == 1  # 不加塞
    r.refresh_from_db()
    assert r.care_level == "半护"  # 拒绝后档案不被第二次参数翻转


# ---- 2. 服务层 ----


@pytest.mark.django_db
def test_review_lists_three_states():
    """盘点三态：无已确认单→待评估（含只有草稿的）、超 12 个月→待复评、
    期内→ok；无床老人（非在住口径）排除"""
    from assessments.services import review_lists

    today = date.today()

    def in_bed(r, room):
        r.bed = _bed(room=room)
        r.save()
        return r

    in_bed(_resident(name="新入住"), "101")
    r_draft = in_bed(_resident(name="只有草稿", room="102"), "102")
    _assess(r_draft, target=50)  # draft 不算已评
    r_due = in_bed(_resident(name="老评估", room="103"), "103")
    _assess(r_due, target=50, d=today - timedelta(days=400)).confirm()
    r_ok = in_bed(_resident(name="近期已评", room="104"), "104")
    _assess(r_ok, target=50, d=today).confirm()
    _resident(name="无床老人", room="901")  # bed=None → 排除

    out = review_lists()
    names = lambda rows: {row["resident"].name for row in rows}  # noqa: E731
    assert names(out["pending_first"]) == {"新入住", "只有草稿"}
    assert names(out["due_review"]) == {"老评估"}
    assert names(out["ok"]) == {"近期已评"}
    assert out["ok"][0]["last_assessed"] == today
    assert "无床老人" not in names(out["pending_first"])


@pytest.mark.django_db
def test_catalog_change_does_not_corrupt_history():
    """快照语义：目录改名/调上限后，历史单总分不漂移（总分落在单上）"""
    from assessments.models import AssessmentItem

    a = _assess(_resident(), target=55)
    before = (a.total_score, a.grade, a.suggested_level)

    item = AssessmentItem.objects.get(name="进食")
    item.name, item.max_score = "进食（改）", 3
    item.save()

    a.refresh_from_db()
    assert (a.total_score, a.grade, a.suggested_level) == before


# ---- 3. API ----


@pytest.fixture
def api_setup(db):
    """两楼各一位在住老人（X-Building 校验用，楼栋行由 _bed 落台账）"""
    r1 = _resident(name="一号老人", room="101")
    r1.bed = _bed(room="101")
    r1.save()
    r2 = _resident(name="二号老人", building="2号楼", room="201")
    r2.bed = _bed(building="2号楼", room="201")
    r2.save()
    return r1, r2


@pytest.mark.django_db
def test_api_create_and_detail_contract(client, api_setup):
    """建单+详情契约钉：26 行明细、总分/等级/建议、schema 层 422、服务层 400、跨楼 403"""
    r1, _r2 = api_setup
    payload = {
        "resident_id": r1.id, "assess_date": "2026-08-01",
        "assessor1": "李医生", "assessor2": "王护士",
        "scores": {str(k): v for k, v in _scores(55).items()},
    }
    out = client.post(
        "/api/assessments/", payload, content_type="application/json"
    ).json()
    assert set(out) == {
        "id", "resident_id", "resident_name", "building", "room", "assess_date",
        "assessor1", "assessor2", "total_score", "grade", "grade_display",
        "suggested_level", "status", "status_display", "final_level",
        "confirmed_by", "confirmed_at", "scores",
    }
    assert out["total_score"] == 60 and out["grade"] == 2
    assert out["grade_display"] == "2级 中度受损"
    assert out["suggested_level"] == "半护"
    assert out["status"] == "draft" and out["status_display"] == "待定级"
    assert len(out["scores"]) == 26
    assert set(out["scores"][0]) == {
        "item_id", "dimension", "name", "score", "max_score",
    }

    bad_date = dict(payload, assess_date="2026/8/1")
    assert client.post(
        "/api/assessments/", bad_date, content_type="application/json"
    ).status_code == 422  # ninja schema 层拒绝（日期格式）

    partial = dict(payload)
    partial["scores"] = dict(list(partial["scores"].items())[:25])
    resp = client.post("/api/assessments/", partial, content_type="application/json")
    assert resp.status_code == 400 and "缺 1 项" in resp.json()["detail"]

    cross = client.post(
        "/api/assessments/", payload, content_type="application/json",
        HTTP_X_BUILDING="2号楼",
    )
    assert cross.status_code == 403


@pytest.mark.django_db
def test_api_list_filter_and_scope(client, api_setup):
    """列表：resident_id/status 过滤 + X-Building scope（裸中文与编码等价）；
    详情：detail 26 行 + 越权 404（不泄露存在性）"""
    r1, r2 = api_setup
    a1 = _assess(r1, target=55)  # draft
    a2 = _assess(r2, target=100)
    a2.confirm()

    items = client.get("/api/assessments/").json()["items"]
    assert len(items) == 2
    assert "scores" not in items[0]  # 列表不带明细

    mine = client.get("/api/assessments/", {"resident_id": r1.id}).json()["items"]
    assert [i["id"] for i in mine] == [a1.id]

    confirmed = client.get("/api/assessments/", {"status": "confirmed"}).json()["items"]
    assert [i["id"] for i in confirmed] == [a2.id]

    for header in ("1号楼", "1%E5%8F%B7%E6%A5%BC"):  # 裸中文与 percent-encode 等价
        scoped = client.get(
            "/api/assessments/", HTTP_X_BUILDING=header
        ).json()["items"]
        assert [i["resident_id"] for i in scoped] == [r1.id]

    detail = client.get(f"/api/assessments/{a2.id}/").json()
    assert len(detail["scores"]) == 26 and detail["status"] == "confirmed"
    assert client.get(
        f"/api/assessments/{a2.id}/", HTTP_X_BUILDING="1号楼"
    ).status_code == 404  # scope_get_or_404：越权与不存在统一 404


@pytest.mark.django_db
def test_api_confirm_guards(client, api_setup):
    """confirm 守卫：缺失 404 / 跨楼 403 / key 路径 operator=api / 再确认 400"""
    r1, _r2 = api_setup
    a = _assess(r1, target=55)

    assert (
        client.post("/api/assessments/99999/confirm/", content_type="application/json")
        .status_code == 404
    )
    cross = client.post(
        f"/api/assessments/{a.id}/confirm/",
        content_type="application/json", HTTP_X_BUILDING="2号楼",
    )
    assert cross.status_code == 403

    ok = client.post(
        f"/api/assessments/{a.id}/confirm/", content_type="application/json"
    ).json()
    assert ok["status"] == "confirmed" and ok["confirmed_by"] == "api"
    r1.refresh_from_db()
    assert r1.care_level == "半护"

    again = client.post(
        f"/api/assessments/{a.id}/confirm/", content_type="application/json"
    )
    assert again.status_code == 400 and "不可重复" in again.json()["detail"]


@pytest.mark.django_db
def test_api_confirm_validation(client, api_setup):
    """confirm 校验：未知档位 400 / 改判无原因 400 / 带原因改判成功"""
    r1, _r2 = api_setup
    a = _assess(r1, target=55)

    bad = client.post(
        f"/api/assessments/{a.id}/confirm/",
        {"final_level": "特护"}, content_type="application/json",
    )
    assert bad.status_code == 400 and "未知护理档" in bad.json()["detail"]

    no_reason = client.post(
        f"/api/assessments/{a.id}/confirm/",
        {"final_level": "失智"}, content_type="application/json",
    )
    assert no_reason.status_code == 400 and "原因" in no_reason.json()["detail"]

    ok = client.post(
        f"/api/assessments/{a.id}/confirm/",
        {"final_level": "失智", "reason": "精神科会诊意见", "confirmed_by": "刘主任"},
        content_type="application/json",
    ).json()
    assert ok["final_level"] == "失智" and ok["confirmed_by"] == "刘主任"
    r1.refresh_from_db()
    assert r1.care_level == "失智"


# ---- 4. 页面 /assessments/ ----


@pytest.mark.django_db
def test_page_anonymous_redirect_and_logged_in(client, api_setup):
    resp = client.get("/assessments/")
    assert resp.status_code == 302 and "/admin/login/" in resp["Location"]

    user = User.objects.create_user(username="viewer", password="x")
    client.force_login(user)
    page = client.get("/assessments/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "入住评估" in html and "GB/T 42195-2022" in html
    assert "评估状态盘点" in html and "新建评估单" in html
    # 在住老人（api_setup 两位）落盘点表
    assert "一号老人" in html and "待评估" in html


@pytest.mark.django_db
def test_page_post_create_and_confirm(client, api_setup):
    """POST 建单（26 个 score_<id> 字段）+ POST 定级（session 员工名落定级人）"""
    from assessments.models import Assessment

    emp = _employee("王医护")
    client.force_login(emp.user)
    r = api_setup[0]

    form = {
        "action": "create", "resident_id": str(r.id), "assess_date": "2026-08-01",
        "assessor1": "王医护", "assessor2": "李护士",
    }
    for i in _items():
        form[f"score_{i.id}"] = str(i.max_score)  # 全满分 → 4级 全护
    resp = client.post("/assessments/", form)
    assert resp.status_code == 302 and f"resident_id={r.id}" in resp["Location"]

    a = Assessment.objects.get(resident=r)
    assert a.total_score == 100 and a.suggested_level == "全护"
    assert a.status == Assessment.Status.DRAFT
    assert a.assessor1_emp == emp  # StaffFkMixin：同名员工自动挂档案

    resp2 = client.post("/assessments/", {
        "action": "confirm", "assessment_id": str(a.id),
        "final_level": "", "reason": "",
    })
    assert resp2.status_code == 302
    a.refresh_from_db()
    assert a.status == Assessment.Status.CONFIRMED and a.final_level == "全护"
    assert a.confirmed_by == "王医护"  # session 员工名，非 username
    r.refresh_from_db()
    assert r.care_level == "全护"


@pytest.mark.django_db
def test_lifecycle_shows_assessment_event(client):
    """生命周期视图：评估事件（总分/等级/评估员/定级）+ 变更事件"""
    user = User.objects.create_user(username="viewer2", password="x")
    client.force_login(user)
    r = _resident(name="生命周期老人", room="101")
    a = _assess(r, target=55, d=date(2026, 7, 1))
    a.confirm(operator="刘主任")

    html = client.get(f"/resident/{r.id}/lifecycle/").content.decode()
    assert "能力评估 60分·2级 中度受损" in html
    assert "评估员 李医生/王护士·定级 半护" in html
    assert "半护 → 半护" in html or "自理 → 半护" in html  # 变更事件行


# ---- 5. admin ----


@pytest.mark.django_db
def test_admin_scoped_queryset_frozen_and_action(api_setup):
    """admin：楼栋过滤 queryset + confirmed 冻结只读 + action 逐单定级（跳过已定级）"""
    from django.contrib.admin import site

    from assessments.admin import AssessmentAdmin
    from assessments.models import Assessment
    from residents.models import CareLevelChange

    r1, r2 = api_setup
    draft = _assess(r1, target=55)  # 1号楼 draft
    done = _assess(r2, target=55)   # 2号楼 已定级
    done.confirm()
    assert CareLevelChange.objects.count() == 1

    boss = User.objects.create_user(username="boss", password="x", is_superuser=True)
    b1_head = _employee("一号楼长", building="1号楼")

    class _Req:
        def __init__(self, user):
            self.user = user

    admin_inst = AssessmentAdmin(Assessment, site)
    assert admin_inst.get_queryset(_Req(boss)).count() == 2
    assert admin_inst.get_queryset(_Req(b1_head.user)).count() == 1  # 只见 1号楼

    ro = admin_inst.get_readonly_fields(_Req(boss), draft)
    assert "resident" not in ro  # draft 可改老人/日期/评估员
    ro_done = admin_inst.get_readonly_fields(_Req(boss), done)
    assert {"resident", "assess_date", "assessor1", "assessor2"} <= set(ro_done)

    # action 逐单：boss 全选 → draft 定级生效、confirmed 报错跳过
    req = _Req(boss)
    from django.contrib.messages.storage.fallback import FallbackStorage

    req.session = "s"
    req._messages = FallbackStorage(req)
    admin_inst.action_confirm(req, Assessment.objects.all())

    draft.refresh_from_db()
    assert draft.status == Assessment.Status.CONFIRMED
    assert CareLevelChange.objects.count() == 2  # 只新增 draft 的一行
    r1.refresh_from_db()
    assert r1.care_level == "半护"

    admin_inst.action_confirm(req, Assessment.objects.all())  # 再跑全跳过
    assert CareLevelChange.objects.count() == 2
