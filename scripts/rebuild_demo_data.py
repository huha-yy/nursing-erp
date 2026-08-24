#!/usr/bin/env python3
"""演示数据重灌 — 保留档案底座，重置并重造「业务动态层」。

分层契约（2026-08-24 定）：
- 档案层不动：登录账号 / 员工 / 老人 / 床位 / 菜品库 / 价目表 / 库存目录
  （id、密码、挂床关系全部保持 → 日常点点点测试的手感不变）
- 动态层重置：点餐 / 月结 / 账单 / 改退餐 / 护理日志 / 健康·作息·用药 /
  任务 / 排班 / 考勤 / 绩效 / 出入库 / 审批 / 巡检 / 报修 / 异常 / 周菜单
- 派生数字一律走真实业务代码（MealFinance.generate_monthly →
  generate_month_bills → settle），脚本从不手写结论 —— 勾稽天然闭合。

真实感五要素：
1. 状态随日期走：历史=已送达，今日=备餐/送餐中，未来=已点餐
2. 人设画像：每人固定口味、固定代点护理员；退餐/改餐留痕（格式与真实
   cancel()/modify_dishes() 一致）
3. 周节律：周末家属探视 → 退餐率约 3× 工作日
4. 月份深度：前两月 + 当月逐月出账，往月全额核销、当月部分核销 → 欠费名单有戏
5. 剧本：
   · 吴桂英(7)·失智 欠费三月 —— 欠费名单榜首
   · 张国栋(1) 护理等级 自理→半护(上月1日)→全护(本月1日)——走真实评估定级：
     create_assessment(26 项国标打分)→confirm() 自动翻转档案+生成关联变更行；
     出账按"当月生效等级"整月计费（先按旧等级出往月账，再升级出当月账）
   · 稳定自理老人补录 400 天前的已确认评估单（from==to 也留痕）→ 盘点"待复评"
   · 杨国华(10) 上月20日身故离院 —— 上月账照出（在世期间），当月起释放
     床位（入住率 35/36）不再出账
   · 尿不湿L码 低于安全线（档案层数量本就如此）+ 待批采购申请

日期全部相对化（以运行日为锚）——任何时候重灌都是"新鲜的活数据"。
固定随机种子——同一 seed 重灌结果一致，可复现、可调试。

运行（脚本会自查 runserver 并拒绝并行）：
    uv run python scripts/rebuild_demo_data.py                # 生产 db.sqlite3
    NURSING_DB=/tmp/x.sqlite3 uv run python scripts/rebuild_demo_data.py  # 临时库演练
"""
import os
import random
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nursing_erp.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.db.models import Count, Sum  # noqa: E402
from django.utils import timezone as djtz  # noqa: E402

from assessments.models import Assessment, AssessmentItem, GradeLevelMap  # noqa: E402
from assessments.services import create_assessment, review_lists  # noqa: E402
from beds.models import Bed  # noqa: E402
from billing.models import FeeRule, MonthlyBill  # noqa: E402
from billing.services import arrears_stats, generate_month_bills, month_summary  # noqa: E402
from incidents.models import IncidentReport  # noqa: E402
from meals.models import Dish, MealFinance, MealModificationLog, MealOrder, WeekMenu  # noqa: E402
from operations.models import (  # noqa: E402
    Approval,
    Inspection,
    InventoryItem,
    MaintenanceOrder,
    StockIn,
    StockOut,
)
from residents.models import (  # noqa: E402
    CareLevelChange,
    DischargeRecord,
    HealthRecord,
    MedicationRecord,
    NursingLog,
    Resident,
    ResidentRoutine,
    TransferRecord,
)
from staff.models import Attendance, Employee, Performance, Schedule, Task  # noqa: E402

SEED = 20260824
ARREARS_ID = 7       # 吴桂英·失智 —— 欠费三月剧本主角
PROMOTION_ID = 1     # 张国栋 —— 自理→半护→全护
DISCHARGE_ID = 10    # 杨国华·失智 —— 上月身故离院
DISCHARGE_DAY = 20   # 上月 20 日

MEALS = ["早餐", "午餐", "晚餐"]
MEAL_HOUR = {"早餐": 7, "午餐": 10, "晚餐": 16}
WEEKEND_CANCEL_P, WEEKDAY_CANCEL_P = 0.15, 0.05

STANDING_REQUESTS = {7: "糖尿病餐", 19: "软食", 2: "少盐", 23: "少油"}  # 固定口味画像
OCCASIONAL_REQUESTS = ["少油", "软一点", "趁热", "分量少一些"]
CANCEL_REASONS_WEEKDAY = ["身体不适没胃口", "不爱吃当天的菜", "体检需要空腹", "牙口不好吃不了"]
CANCEL_REASONS_WEEKEND = ["家属接出去吃了", "回家过周末", "家属探视带了饭"]
MODIFY_REASONS = ["老人要求换菜", "牙口不好换软食", "同菜吃腻了换口味"]

DISH_RULES = [  # 菜品库纠偏（档案层既有 94 道菜几乎全标"素菜"）——按关键词重分类
    ("粥", "主食"), ("饭", "主食"), ("馒头", "主食"),
    ("花卷", "主食"), ("包子", "主食"), ("面条", "主食"),
    ("汤", "汤"), ("羹", "汤"),
    ("鱼", "荤菜"), ("鸡", "荤菜"), ("鸭", "荤菜"), ("肉", "荤菜"), ("虾", "荤菜"),
    ("排骨", "荤菜"), ("蛋", "荤菜"),
    ("拌", "小菜"), ("凉", "小菜"),
]


def shift_month(d: date, k: int) -> date:
    """月份平移，返回该月 1 号。"""
    y, m = d.year, d.month - 1 + k
    y, m = y + m // 12, m % 12 + 1
    return date(y, m, 1)


def month_str(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_end(d: date) -> date:
    return shift_month(d, 1) - timedelta(days=1)


def aware(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), tzinfo=djtz.get_current_timezone())


def fail(msg: str):
    raise SystemExit(f"✗ 自检失败：{msg}")


def check(cond, msg: str):
    if not cond:
        fail(msg)


def level_timeline(anchor: date):
    """评估定级时间线（相对锚点）：(resident_id, 日期, 目标档, 目标总分, 原因, 经办人)。

    每行 = 一张评估单：synth_scores(目标总分) 打 26 项 → 建议档应恰为目标档
    （55→2级半护 / 75→3级全护，±1 舍入不跨段），confirm(final_level=目标档)。
    from 档不再手写——confirm 时取老人当时档位，链条自然衔接。
    """
    return [
        (2, shift_month(anchor, -2).replace(day=15), "半护", 55,
         "术后康复期，需协助起居", "张主任"),
        (PROMOTION_ID, shift_month(anchor, -1).replace(day=1), "半护", 55,
         "行动能力下降，需部分生活协助", "刘主任"),
        (PROMOTION_ID, anchor.replace(day=1), "全护", 75,
         "病情加重，需全天照护", "刘主任"),
    ]


def pool_pick(pools: dict, cat: str, rot: int, k: int) -> list:
    """从分类池确定性取 k 道（轮转抽样）；池空则退回素菜池。"""
    pool = pools.get(cat) or pools.get("素菜") or []
    k = min(k, len(pool))
    return [pool[(rot + i) % len(pool)][0] for i in range(k)]


def status_for(d: date, meal: str, anchor: date, now) -> str:
    if d < anchor:
        return "delivered"
    if d > anchor:
        return "ordered"
    h = now.hour
    if meal == "早餐":
        return "delivered"
    if meal == "午餐":
        return "preparing" if h < 11 else ("delivering" if h < 14 else "delivered")
    return "ordered" if h < 15 else ("preparing" if h < 17 else "delivered")


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def main() -> None:
    # runserver 守卫只管默认库（生产 db.sqlite3）；NURSING_DB 指向临时库时
    # 写的是另一个文件，与运行中的服务互不相扰，放行
    if "--force" not in sys.argv and not os.environ.get("NURSING_DB"):
        pg = subprocess.run(["pgrep", "-f", "manage.py runserver"], capture_output=True)
        if pg.returncode == 0:
            sys.exit("✗ 检测到 runserver 正在运行——先停服再重灌（或 --force 自担风险）")

    anchor = date.today()
    months = [month_str(shift_month(anchor, k)) for k in (-2, -1, 0)]
    span_start = shift_month(anchor, -2)
    span_end = anchor + timedelta(days=2)
    now = djtz.now()
    db_name = connection.settings_dict["NAME"]
    print(f"=== 演示数据重灌 anchor={anchor} 月份={months} 库={db_name} ===")

    # ── 0. 预检：档案层完整、价目齐、账号可用 ─────────────────────
    residents = list(Resident.objects.order_by("id"))
    employees = list(Employee.objects.order_by("id"))
    check(len(residents) == 36, f"老人应 36 位，实际 {len(residents)}")
    check(len(employees) >= 40, f"员工应 ≥40，实际 {len(employees)}")
    meal_price = FeeRule.get_meal_price()
    bed_fee = FeeRule.get_bed_fee()
    for level in ("自理", "半护", "全护", "失智"):
        FeeRule.get_nursing_fee(level)  # 缺行抛 FeeRuleMissing
    for uname in ("b1_liu", "wang_jianguo"):
        u = User.objects.filter(username=uname).first()
        check(u is not None and u.check_password("123456"), f"账号 {uname} 缺失或密码不对")
    check(User.objects.filter(username="admin").exists(), "admin 账号缺失")
    catalog = list(AssessmentItem.objects.filter(is_active=True))
    check(len(catalog) == 26, f"评估目录应 26 项（国标），实际 {len(catalog)}")
    check(GradeLevelMap.objects.count() == 5, "等级映射表应 5 行")

    def synth_scores(target: int) -> dict[int, int]:
        """按目标总分等比例打 26 项——建单算出的建议档即目标档。"""
        return {i.id: round(i.max_score * target / 100) for i in catalog}

    print(f"  预检通过：36 老老 / {len(employees)} 员工 / 价目 床{bed_fee} 餐{meal_price}"
          " / 评估目录 26 项·映射 5 行")

    with transaction.atomic():
        # ── 1. 清空动态层（ORM delete 走级联，M2M/日志一并清）─────
        for model in (
            MealOrder, MealFinance, WeekMenu, MonthlyBill,
            NursingLog, HealthRecord, MedicationRecord, ResidentRoutine,
            Assessment,  # 级联清 AssessmentScore 明细
            CareLevelChange, TransferRecord, DischargeRecord,
            Task, Attendance, Schedule, Performance,
            StockIn, StockOut, MaintenanceOrder, Inspection, Approval,
            IncidentReport,
        ):
            n, _ = model.objects.all().delete()
            if n:
                print(f"  清空 {model.__name__}: -{n}")

        # ── 2. 档案层校正（幂等）───────────────────────────────────
        fixed = 0
        for dish in Dish.objects.all():
            for kw, cat in DISH_RULES:
                if kw in dish.name and dish.category != cat:
                    dish.category = cat
                    dish.save(update_fields=["category"])
                    fixed += 1
                    break
        promo = Resident.objects.get(pk=PROMOTION_ID)
        promo.care_level = "自理"  # 每轮重灌回到时间线起点（首评前基线）重新走
        promo.save(update_fields=["care_level"])
        print(f"  档案校正：菜品重分类 {fixed} 道；{promo.name} 等级重置为 自理")

        # ── 3. 周菜单（覆盖整个点餐跨度）──────────────────────────
        dish_pools = {
            c: list(Dish.objects.filter(category=c, is_available=True).values_list("id", "name"))
            for c in ("荤菜", "素菜", "主食", "汤", "小菜")
        }
        staple_set = {i for i, _ in dish_pools.get("主食", [])}
        dish_names = {i: n for pool in dish_pools.values() for i, n in pool}
        menu_map: dict[tuple[date, str], list[int]] = {}
        menus, menu_links = [], []
        ws = span_start - timedelta(days=span_start.weekday())
        wk = 0
        while ws <= span_end:
            for di, day_name in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"]):
                d = ws + timedelta(days=di)
                for mi, meal in enumerate(MEALS):
                    rot = (wk * 7 + di) * 3 + mi
                    if meal == "早餐":
                        picks = (pool_pick(dish_pools, "主食", rot, 2)
                                 + pool_pick(dish_pools, "小菜", rot, 1))
                    elif meal == "午餐":
                        picks = (pool_pick(dish_pools, "荤菜", rot, 2)
                                 + pool_pick(dish_pools, "素菜", rot, 2)
                                 + pool_pick(dish_pools, "主食", rot, 1)
                                 + pool_pick(dish_pools, "汤", rot, 1))
                    else:
                        picks = (pool_pick(dish_pools, "荤菜", rot, 1)
                                 + pool_pick(dish_pools, "素菜", rot, 2)
                                 + pool_pick(dish_pools, "主食", rot, 1)
                                 + pool_pick(dish_pools, "汤", rot, 1))
                    m = WeekMenu(week_start=ws, day=day_name, meal_type=meal)
                    menus.append(m)
                    menu_links.append((m, picks))
                    menu_map[(d, meal)] = picks
            wk += 1
            ws += timedelta(days=7)
        WeekMenu.objects.bulk_create(menus)
        WeekMenu.dishes.through.objects.bulk_create(
            [WeekMenu.dishes.through(weekmenu_id=m.pk, dish_id=d)
             for m, picks in menu_links for d in picks]
        )
        print(f"  周菜单：{len(menus)} 行（{wk} 周）")

        # ── 4. 点餐事实（人设驱动；一老人一餐一单，天然过防重约束）─
        cgs_by_building: dict[str, list[Employee]] = {}
        for e in employees:
            if e.is_caregiver and e.building:
                cgs_by_building.setdefault(e.building, []).append(e)
        discharge_date = shift_month(anchor, -1).replace(day=DISCHARGE_DAY)
        persona = {}
        for r in residents:
            p = random.Random(f"{SEED}-persona-{r.id}")
            persona[r.id] = {
                "skip": {"早餐": p.uniform(0.06, 0.18), "午餐": p.uniform(0.01, 0.03),
                         "晚餐": p.uniform(0.03, 0.08)},
                "cancel_bias": 1.5 if r.id == ARREARS_ID else 1.0,  # 失智老人拒食倾向
                "standing": STANDING_REQUESTS.get(r.id, ""),
            }
        orders, order_links, mod_logs, order_times, mod_times = [], [], [], [], []
        for r in residents:
            p = random.Random(f"{SEED}-orders-{r.id}")
            cgs = cgs_by_building.get(r.building, [])
            for d in daterange(span_start, span_end):
                if r.id == DISCHARGE_ID and d >= discharge_date:
                    continue  # 身故离院后不再点餐
                for meal in MEALS:
                    if p.random() < persona[r.id]["skip"][meal]:
                        continue
                    picks = menu_map.get((d, meal))
                    if not picks:
                        continue
                    staples = [x for x in picks if x in staple_set]
                    others = [x for x in picks if x not in staple_set]
                    chosen = staples[:1] + p.sample(others, k=min(len(others), p.choice([1, 2])))
                    status = status_for(d, meal, anchor, now)
                    reason = ""
                    if status != "ordered":  # 只有已发生/进行中的餐才可能被退/改
                        cancel_p = (WEEKEND_CANCEL_P if d.weekday() >= 5 else WEEKDAY_CANCEL_P)
                        cancel_p *= persona[r.id]["cancel_bias"]
                        if p.random() < cancel_p:
                            is_weekend = d.weekday() >= 5
                            status, reason = "cancelled", p.choice(
                                CANCEL_REASONS_WEEKEND if is_weekend else CANCEL_REASONS_WEEKDAY
                            )
                        elif p.random() < 0.025:
                            swap = pool_pick(dish_pools, "素菜", d.day * 31 + r.id, 1)
                            if swap:
                                old = dish_names.get(chosen[-1], "?")
                                chosen = chosen[:-1] + swap
                                status, reason = "modified", (
                                    f"原: {old} → 新: {dish_names.get(swap[0], '?')}"
                                    f" ({p.choice(MODIFY_REASONS)})"
                                )
                    standing = persona[r.id]["standing"]
                    occasional = p.choice(OCCASIONAL_REQUESTS) if p.random() < 0.04 else ""
                    requests = standing or occasional
                    cg = cgs[(r.id // 6 + d.isoweekday()) % len(cgs)] if cgs else None
                    created = min(aware(d - timedelta(days=1), MEAL_HOUR[meal], 30), now)
                    updated = min(created + timedelta(hours=3), now) if reason else created
                    o = MealOrder(
                        resident_id=r.id, date=d, meal_type=meal,
                        special_requests=requests[:200], status=status,
                        ordered_by=cg.name if cg else "", ordered_by_emp=cg,
                        created_at=created, updated_at=updated,
                    )
                    orders.append(o)
                    order_links.append((o, chosen))
                    order_times.append((created, updated))
                    if reason:
                        mod_logs.append(MealModificationLog(
                            order=o, action="cancel" if status == "cancelled" else "modify",
                            reason=reason, changed_by=cg.name if cg else "",
                            changed_by_emp=cg,
                        ))
                        mod_times.append(min(created + timedelta(hours=3), now))
        MealOrder.objects.bulk_create(orders, batch_size=500)
        check(all(o.pk for o in orders), "bulk_create 未回填主键")
        MealOrder.dishes.through.objects.bulk_create(
            [MealOrder.dishes.through(mealorder_id=o.pk, dish_id=d)
             for o, picks in order_links for d in picks],
            batch_size=1000,
        )
        MealModificationLog.objects.bulk_create(mod_logs, batch_size=500)
        check(all(m.pk for m in mod_logs), "改退日志未回填主键")
        # auto_now_add 陷阱：bulk_create 时 pre_save 会覆盖构造参数里的时间，
        # 下单/改退时间必须事后回填（Django 连接的 sqlite 适配器与 ORM 同源，
        # 时区转换行为一致）
        with connection.cursor() as cur:
            cur.executemany(
                "UPDATE meals_mealorder SET created_at=?, updated_at=? WHERE id=?",
                [(c, u, o.pk) for (c, u), o in zip(order_times, orders, strict=True)],
            )
            cur.executemany(
                "UPDATE meals_mealmodificationlog SET changed_at=? WHERE id=?",
                [(t, m.pk) for t, m in zip(mod_times, mod_logs, strict=True)],
            )
        n_cancel = sum(1 for o in orders if o.status == "cancelled")
        n_modify = sum(1 for o in orders if o.status == "modified")
        print(f"  点餐：{len(orders)} 单（退餐 {n_cancel} / 改餐 {n_modify}）")

        # ── 5. 其他域（轻量、相对日期）────────────────────────────
        gen_other_domains(anchor, residents, employees, cgs_by_building)

        # ── 6. 逐月出账：等级时间线 → 出账 → 核销 → 回填核销时间 ──
        timeline = level_timeline(anchor)
        applied = set()
        for mi, m in enumerate(months):
            if mi == 2:
                # 上月账已出完核销完 → 身故离院 + 转区留痕（历史日期）。
                # DischargeRecord.save() 新建时会自动 update(bed=None) 释放床位
                # （绕过 Resident.save，楼栋字符串缓存保留为"最后已知位置"），
                # 之后生成的当月账自然排除杨国华（无床无点餐）
                DischargeRecord.objects.create(
                    resident=Resident.objects.get(pk=DISCHARGE_ID), discharge_type="身故",
                    discharge_date=discharge_date, reason="因病离世",
                )
                TransferRecord.objects.create(
                    resident=Resident.objects.get(pk=PROMOTION_ID),
                    from_zone="自理区", to_zone="介护区",
                    transfer_date=anchor.replace(day=1),
                    reason="随护理等级由半护转全护，迁入介护区",
                )
            m_end = month_end(date.fromisoformat(m + "-01"))
            for idx, (rid, cdate, to_l, target, reason, by) in enumerate(timeline):
                if idx in applied or cdate > m_end:
                    continue
                r = Resident.objects.get(pk=rid)
                # 走真实评估定级：26 项打分 → 建议档=目标档 → confirm 原子翻转
                # 档案 + 生成关联变更行（from 取当时档位，链条自然衔接）
                a = create_assessment(r, cdate, "李护士", "王护士", synth_scores(target))
                check(a.suggested_level == to_l,
                      f"{r.name} 目标总分 {target} 算出建议 {a.suggested_level}，"
                      f"应为 {to_l}（目标分漂移跨段？）")
                a.confirm(operator=by, final_level=to_l, reason=reason)
                # StaffFkMixin 遇重名（刘主任×2）留空 → 按既有定夺回填员工档案
                emp = (Employee.objects.filter(name=by).exclude(building="")
                       .order_by("id").first())
                CareLevelChange.objects.filter(assessment=a).update(changed_by_emp=emp)
                applied.add(idx)
                print(f"  评估定级：{r.name} {a.total_score}分·{a.grade}级 → {to_l}"
                      f"（{cdate}，出账 {m} 前）")
            stats = generate_month_bills(m)
            bills = list(MonthlyBill.objects.filter(month=m).select_related("resident"))
            settle_ids, settle_rids = [], []
            for b in bills:
                if b.resident_id == ARREARS_ID:
                    continue  # 欠费剧本主角：永远不核销
                if mi == 2 and b.resident_id % 3 == 0:
                    continue  # 当月再留一批未缴 → 欠费名单有层次
                b.settle(operator="孙财务")
                settle_ids.append(b.pk)
                settle_rids.append(b.resident_id)
            if settle_ids:
                # 往月核销时间 = 月末+2天 10:30；钳制不晚于当下（当月"最近刚缴"）
                pay_dt = min(aware(m_end + timedelta(days=2), 10, 30),
                             now - timedelta(hours=1))
                with connection.cursor() as cur:
                    cur.executemany(
                        "UPDATE billing_monthlybill SET settled_at=? WHERE id=?",
                        [(pay_dt, i) for i in settle_ids],
                    )
                MealFinance.objects.filter(resident_id__in=settle_rids, month=m).update(paid=True)
            print(f"  出账 {m}：{stats['generated']} 单 合计 ¥{stats['total']}"
                  f"（核销 {len(settle_ids)} / 跳过已缴 {stats['skipped_paid']}）")

        # ── 6.4 复评剧本：稳定自理老人 400 天前已定级（from==to 也留痕）──
        # 目标 10 分=0级→建议自理==现档，不扰动已出的账；盘点页「待复评」有内容
        stale = (Resident.objects.exclude(bed=None)
                 .exclude(id__in=(PROMOTION_ID, 2, ARREARS_ID, DISCHARGE_ID))
                 .filter(care_level="自理").order_by("id").first())
        check(stale is not None, "找不到可补录复评的自理在住老人")
        a_stale = create_assessment(stale, anchor - timedelta(days=400),
                                    "李护士", "王护士", synth_scores(10))
        a_stale.confirm(operator="刘主任")
        print(f"  复评补录：{stale.name} 400 天前已定级"
              f"（{a_stale.total_score}分·{a_stale.grade}级 自理，from==to 留痕）")

        # ── 6.5 自检断言（留在事务内：失败即整体回滚，生产库不留半套数据）─
        run_assertions(anchor, months, meal_price, bed_fee, discharge_date, stale.name)

    # ── 8. 数字面板 ────────────────────────────────────────────
    print("\n=== 数字面板 ===")
    for m in months:
        s = month_summary(m)
        print(f"  {m}：账单 {len(s['bills'])} 张 应收 ¥{s['receivable']}"
              f" 已缴 ¥{s['received']} 欠缴 ¥{s['outstanding']}（已缴 {s['paid_count']} 张）")
    arr = arrears_stats(months[-1])
    print(f"  欠费名单：{arr['resident_count']} 人 合计 ¥{arr['total_outstanding']}")
    for row in arr["rows"][:3]:
        print(f"    {row['resident__name']}（{row['resident__building']} {row['resident__room']}）"
              f" 欠 {row['unpaid_months']} 个月 ¥{row['outstanding']} 最早 {row['oldest_month']}")
    rv = review_lists()
    print(f"  评估盘点：待评估 {len(rv['pending_first'])} / 待复评 {len(rv['due_review'])}"
          f" / 期内已评 {len(rv['ok'])}")
    occ = Resident.objects.exclude(bed=None).count()
    total_beds = Bed.objects.count()
    low = [i.name for i in InventoryItem.objects.all() if i.is_low_stock]
    print(f"  入住率：{occ}/{total_beds}（{occ / total_beds:.0%}）")
    print(f"  低库存告警：{'、'.join(low) if low else '无'}")
    print(f"  点餐总量：{MealOrder.objects.count()} 单"
          f" / 改退留痕 {MealModificationLog.objects.count()} 条")
    print("=== 重灌完成 ===")


def gen_other_domains(anchor, residents, employees, cgs_by_building) -> None:
    """护理日志/健康/作息/用药/任务/排班/考勤/绩效/出入库/审批/巡检/报修/异常。"""
    p = random.Random(f"{SEED}-misc")

    def cg_of(r):
        cgs = cgs_by_building.get(r.building, [])
        return cgs[r.id % len(cgs)] if cgs else None

    # 护理日志：近 10 天；等级越高翻身/如厕类越多
    cat_by_level = {"自理": ["feeding", "hygiene", "vital_signs", "rehab"],
                    "半护": ["feeding", "hygiene", "toilet", "medicine", "vital_signs"],
                    "全护": ["turning", "toilet", "feeding", "hygiene", "medicine"],
                    "失智": ["feeding", "hygiene", "toilet", "turning", "vital_signs"]}
    logs = []
    for r in residents:
        cg = cg_of(r)
        cats = cat_by_level[r.care_level]
        for back in range(10):
            if (r.id + back) % 3:  # 每人约 2/3 的天数有日志
                continue
            logs.append(NursingLog(
                resident=r, log_date=anchor - timedelta(days=back),
                category=cats[(back + r.id) % len(cats)],
                detail=p.choice(["情况平稳，按护理计划执行。", "进食正常，餐后协助漱口。",
                                 "协助如厕一次，无异常。", "按时翻身，皮肤完好。",
                                 "生命体征测量正常并记录。"]),
                staff_name=cg.name if cg else "", staff_emp=cg,
            ))
    NursingLog.objects.bulk_create(logs, batch_size=500)

    # 健康记录：全员近 5 天
    hrs = []
    for r in residents:
        rp = random.Random(f"{SEED}-hr-{r.id}")
        for back in range(5):
            hrs.append(HealthRecord(
                resident=r, record_date=anchor - timedelta(days=back),
                blood_pressure=f"{116 + rp.randrange(0, 18)}/{70 + rp.randrange(0, 10)}",
                blood_sugar=Decimal(f"{4.6 + rp.randrange(0, 14) * 0.1:.1f}"),
                heart_rate=64 + rp.randrange(0, 16),
                weight=Decimal(f"{50 + rp.randrange(0, 20) + rp.randrange(0, 10) * 0.1:.1f}"),
                temperature=Decimal(f"{36.2 + rp.randrange(0, 5) * 0.1:.1f}"),
                note="指标平稳" if rp.random() < 0.8 else "血压偏高，持续关注",
            ))
    HealthRecord.objects.bulk_create(hrs, batch_size=500)

    # 作息记录：12 位老人近 4 天
    rts = []
    for r in residents[:12]:
        for back in range(4):
            rts.append(ResidentRoutine(
                resident=r, log_date=anchor - timedelta(days=back),
                wake_up=time(6, 30), sleep=time(21, 0),
                breakfast=(r.id + back) % 3 != 0, lunch=True, dinner=(r.id + back) % 5 != 0,
                activities=p.choice(["散步", "打太极", "看电视", "做手工", "晒太阳"]),
                mood=p.choice(["良好", "平稳", "愉悦", "一般"]),
            ))
    ResidentRoutine.objects.bulk_create(rts, batch_size=500)

    # 用药记录：常见老年慢病用药，1/4 已停用留痕
    meds = [("苯磺酸氨氯地平片", "5mg", "qd"), ("二甲双胍缓释片", "0.5g", "bid"),
            ("阿托伐他汀钙片", "20mg", "qd"), ("硝酸甘油片", "0.5mg", "prn"),
            ("奥美拉唑肠溶胶囊", "20mg", "qd"), ("复方丹参滴丸", "10丸", "tid"),
            ("格列美脲片", "2mg", "qd"), ("氢氯噻嗪片", "25mg", "qd")]
    mrs = []
    for i, r in enumerate(residents):
        for name, dose, freq in meds[: 1 + r.id % 3]:
            start = shift_month(anchor, -2) + timedelta(days=(r.id * 3) % 25)
            stopped = i % 4 == 0
            mrs.append(MedicationRecord(
                resident=r, medicine_name=name, dosage=dose, frequency=freq,
                start_date=start,
                end_date=start + timedelta(days=30) if stopped else None,
                is_active=not stopped,
                note="疗程结束停用" if stopped else "",
            ))
    MedicationRecord.objects.bulk_create(mrs, batch_size=500)

    # 任务：楼栋主任派给本楼护理员
    leads = [e for e in employees if not e.is_caregiver and e.building]
    tasks = []
    task_seed = [
        ("护送老人体检", "护送本楼 5 位老人到医务室体检", -1, True),
        ("楼栋送餐", "午间为 3 层老人送餐", 0, True),
        ("公共区域消毒", "对本楼公共区域进行消毒", -2, True),
        ("整理老人档案", "更新本周老人用药记录", 1, False),
        ("库存盘点", "盘点护理耗材库存并录入系统", 0, True),
        ("组织老人活动", "下午组织老人在活动室做手工", 0, False),
        ("维修跟进", "跟进本楼轮椅维修进度", -3, True),
        ("新员工带教", "带教新入职护理员熟悉流程", 2, False),
    ]
    for i, (title, content, dd, done) in enumerate(task_seed):
        lead = leads[i % len(leads)]
        cgs = cgs_by_building.get(lead.building, [])
        if not cgs:
            continue  # assignee 非空外键，无护理员的楼栋不造任务
        tasks.append(Task(
            assigner_name=lead.name, assigner_emp=lead,
            assignee=cgs[i % len(cgs)],
            title=title, content=content,
            deadline=anchor + timedelta(days=dd), is_completed=done,
        ))
    Task.objects.bulk_create(tasks, batch_size=100)

    # 排班+考勤：护理员近 7 天 + 未来 3 天（做六休一，白/夜轮换）
    scheds, atts = [], []
    for bld, cgs in cgs_by_building.items():
        floors = sorted({r.floor for r in residents if r.building == bld})
        for cg in cgs:
            for off in range(-7, 4):
                d = anchor + timedelta(days=off)
                if (cg.id + d.toordinal()) % 7 == 6:
                    continue  # 休一天
                night = (cg.id + d.isocalendar()[1]) % 2 == 0
                scheds.append(Schedule(
                    employee=cg, date=d, shift="夜班" if night else "白班",
                    building=bld, floor=floors[cg.id % len(floors)] if floors else "",
                    task_note="夜间巡房两次" if night else "协助老人午晚餐",
                ))
                if d < anchor:
                    base_h = 19 if night else 7
                    atts.append(Attendance(
                        employee=cg, date=d,
                        clock_in=aware(d, base_h, 2 + cg.id % 5),
                        clock_out=(aware(d, (base_h + 12) % 24, 5 + cg.id % 7)
                                   + (timedelta(days=1) if night else timedelta())),
                    ))
    Schedule.objects.bulk_create(scheds, batch_size=500)
    Attendance.objects.bulk_create(atts, batch_size=500)

    # 绩效：主任/组长 近两月
    perf = []
    reviewers = [e for e in employees if "主任" in e.name or "组长" in e.name][:12]
    for back in (2, 1):
        m = month_str(shift_month(anchor, -back))
        for e in reviewers:
            att_s = 90 + (e.id * 7 + back) % 10
            qty_s = 88 + (e.id * 11 + back) % 12
            perf.append(Performance(
                employee=e, month=m, attendance_score=att_s, quality_score=qty_s,
                total_score=round((att_s + qty_s) / 2),
                comment="工作认真负责" if qty_s >= 94 else "",
            ))
    Performance.objects.bulk_create(perf, batch_size=100)

    # 出入库：近一周（bulk 绕过 save 钩子 → 不改档案层库存数量，低库存状态保持）
    items = list(InventoryItem.objects.order_by("id"))
    suppliers = ["杭州康养供应链有限公司", "浙江医疗器械批发", "洁达消毒用品"]
    sins = [StockIn(item=items[(i + 1) % len(items)], quantity=qty, supplier=suppliers[i % 3],
                    date=anchor + timedelta(days=off), operator=op)
            for i, (off, qty, op) in enumerate([
                (-6, 100, "陈总务"), (-6, 80, "陈总务"), (-5, 500, "赵总务"), (-5, 1000, "赵总务"),
                (-4, 50, "陈总务"), (-3, 300, "陈总务"), (-2, 30, "赵总务"), (-1, 50, "陈总务")])]
    souts = [StockOut(item=items[(i * 2 + 3) % len(items)], quantity=qty, taken_by=taker,
                      date=anchor + timedelta(days=off))
             for i, (off, qty, taker) in enumerate([
                 (-5, 20, "李护士"), (-5, 100, "王护士"), (-4, 200, "王护士"), (-4, 10, "陈总务"),
                 (-3, 50, "张护士"), (-2, 5, "李护士"), (-2, 10, "王护士"), (-1, 30, "张护士")])]
    StockIn.objects.bulk_create(sins, batch_size=100)
    StockOut.objects.bulk_create(souts, batch_size=100)

    # 审批 / 巡检 / 报修 / 异常上报
    Approval.objects.bulk_create([
        Approval(applicant_name=n, approval_type=t, title=ti, content=c, status=s)
        for n, t, ti, c, s in [
            ("陈总务", "purchase", "采购尿不湿L码",
             "尿不湿L码库存低于安全线，申请采购 200 包。", "pending"),
            ("赵总务", "purchase", "采购一次性口罩",
             "全院口罩库存告急，申请采购 2000 只。", "pending"),
            ("张护士", "leave", "张护士请假申请", "家中急事，申请下周三请假一天。", "approved"),
            ("李护士", "leave", "李护士调休申请", "申请下周五调休。", "pending"),
            ("王护士", "reimburse", "护理耗材费用报销",
             "3号楼护理耗材采购垫付 860 元，申请报销。", "pending"),
            ("陈总务", "purchase", "采购消毒液", "全院清洁消毒用品补充采购。", "approved"),
        ]
    ], batch_size=100)
    Inspection.objects.bulk_create([
        Inspection(inspector_name=n, area=a, date=anchor + timedelta(days=off),
                   result=res, note=note)
        for n, a, off, res, note in [
            ("王建国", "1号楼餐厅", -1, "合格", "地面整洁，餐具消毒达标"),
            ("李卫东", "3号楼公共区域", -1, "合格", "走廊扶手已消毒"),
            ("王建国", "2号楼卫生间", -2, "不合格", "2楼男卫地面有水渍，已通知保洁"),
            ("刘主任", "食堂后厨", -2, "合格", "生熟分区规范"),
            ("吴主任", "1号楼活动室", -3, "合格", "通风良好"),
            ("李卫东", "3号楼洗衣房", -3, "不合格", "角落堆放杂物，已整改"),
        ]
    ], batch_size=100)
    MaintenanceOrder.objects.bulk_create([
        MaintenanceOrder(
            equipment_name=eq, location=loc, fault_description=f,
            reported_by=by, status=st,
            resolved_at=aware(anchor - timedelta(days=1), 15) if st == "done" else None,
        )
        for eq, loc, f, by, st in [
            ("轮椅", "3号楼2层", "轮椅左轮松动，推起来有异响", "张护士", "in_progress"),
            ("血压计", "护理站", "血压计读数不准，需要校准", "李护士", "pending"),
            ("热水器", "2号楼淋浴间", "热水器不出热水", "王护士", "done"),
            ("电梯", "1号楼", "电梯按键不灵敏", "刘主任", "pending"),
            ("制氧机", "3号楼3层", "制氧机报警灯常亮", "张护士", "in_progress"),
            ("呼叫器", "5号楼2层", "呼叫器无响应", "钱小红", "pending"),
        ]
    ], batch_size=100)
    incs = []
    for r, cat, sev, desc, handled in [
        (residents[ARREARS_ID - 1], "refuse_eat", "warning",
         "午餐拒食，护理人员耐心劝导后进食少量", True),
        (residents[3], "fall", "danger", "走廊不慎跌倒，已送医检查，无骨折", True),
        (residents[18], "mood", "info", "思念家属情绪低落，已联系家属视频", True),
        (residents[25], "skin", "warning", "骶尾部皮肤发红，已开始减压护理", True),
        (residents[ARREARS_ID - 1], "refuse_eat", "info", "早餐进食少，持续观察", False),
        (residents[10], "wander", "warning", "在楼道徘徊寻找出口，已引导回房", False),
    ]:
        cg = cg_of(r)
        incs.append(IncidentReport(
            resident=r, category=cat, severity=sev, description=desc,
            handled=handled, handled_by=cg.name if cg else "",
            handled_by_emp=cg if cg else None,
            handled_at=djtz.now() - timedelta(hours=3) if handled else None,
        ))
    IncidentReport.objects.bulk_create(incs, batch_size=100)


def run_assertions(anchor: date, months: list, meal_price: Decimal, bed_fee: Decimal,
                   discharge_date: date, stale_name: str = "") -> None:
    print("\n=== 自检断言 ===")
    # 1. 无有效重复槽位
    dup = (MealOrder.objects.exclude(status="cancelled")
           .values("resident", "date", "meal_type").annotate(n=Count("id")).filter(n__gt=1))
    check(not dup.exists(), f"存在有效重复槽位 {dup.count()} 个")

    # 2. 状态与日期一致
    past_bad = MealOrder.objects.filter(
        status__in=["preparing", "delivering", "delivered"], date__gt=anchor).count()
    fut_bad = MealOrder.objects.filter(status="ordered", date__lt=anchor).count()
    check(past_bad == 0 and fut_bad == 0,
          f"状态/日期错位：进行态越界 {past_bad}，已点餐落在过去 {fut_bad}")

    # 3. 逐人逐月：月结 = 点餐事实 × 单价（勾稽核心）
    for f in MealFinance.objects.select_related("resident"):
        orders = MealOrder.objects.filter(resident=f.resident, date__startswith=f.month)
        total, canc = orders.count(), orders.filter(status="cancelled").count()
        expect = (total - canc) * meal_price
        check(f.total_meals == total and f.cancelled == canc and f.amount == expect,
              f"{f.resident.name} {f.month} 月结与点餐不符："
              f"月结 {f.total_meals}/{f.cancelled}/{f.amount} vs 事实 {total}/{canc}/{expect}")

    # 4. 逐月：Σ月结 = Σ账单餐费；每张账单合计 = 三费之和
    for m in months:
        fin = MealFinance.objects.filter(month=m).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        bills = MonthlyBill.objects.filter(month=m)
        bmeal = bills.aggregate(s=Sum("meal_fee"))["s"] or Decimal("0")
        check(fin == bmeal, f"{m} Σ月结 {fin} ≠ Σ账单餐费 {bmeal}")
        for b in bills.select_related("resident"):
            check(b.total == b.bed_fee + b.nursing_fee + b.meal_fee,
                  f"{b.resident.name} {m} 账单合计不平")

    # 5. 当月床位+护理 = 在住老人价目合计（等级时间线终态）
    expect_bn = sum(
        (bed_fee + FeeRule.get_nursing_fee(r.care_level)).quantize(Decimal("0.01"))
        for r in Resident.objects.exclude(bed=None)
    )
    got = MonthlyBill.objects.filter(month=months[-1]).aggregate(
        b=Sum("bed_fee"), n=Sum("nursing_fee"))
    check((got["b"] or 0) + (got["n"] or 0) == expect_bn,
          f"当月床位+护理 {(got['b'] or 0) + (got['n'] or 0)} ≠ 价目推算 {expect_bn}")

    # 6. 欠费榜首 = 剧本主角，三个月未缴
    arr = arrears_stats(months[-1])
    top = arr["rows"][0]
    check(top["resident_id"] == ARREARS_ID and top["unpaid_months"] == 3,
          f"欠费榜首应为 {ARREARS_ID} 号欠 3 个月，"
          f"实际 {top['resident__name']} {top['unpaid_months']} 个月")
    check(not MonthlyBill.objects.filter(resident_id=ARREARS_ID, status="paid").exists(),
          "欠费主角存在已缴账单")

    # 7. 身故老人：当月无账单、床位已释放；上月账在且已核销；离院后无点餐
    dead = Resident.objects.get(pk=DISCHARGE_ID)
    check(dead.bed is None, "身故老人床位未释放")
    check(not MonthlyBill.objects.filter(resident_id=DISCHARGE_ID, month=months[-1]).exists(),
          "身故老人当月不应出账")
    prev_bill = MonthlyBill.objects.filter(resident_id=DISCHARGE_ID, month=months[1]).first()
    check(prev_bill is not None and prev_bill.status == "paid", "身故老人上月账缺失或未核销")
    check(not MealOrder.objects.filter(resident_id=DISCHARGE_ID, date__gte=discharge_date).exists(),
          "身故老人离院后仍有点餐")

    # 8. 等级剧本：张国栋三个月护理费 = 自理/半护/全护价目
    promo_fees = {
        b.month: b.nursing_fee
        for b in MonthlyBill.objects.filter(resident_id=PROMOTION_ID)
    }
    want = [FeeRule.get_nursing_fee(lv) for lv in ("自理", "半护", "全护")]
    got_fees = [promo_fees.get(m) for m in months]
    check(got_fees == want, f"张国栋护理费时间线 {got_fees} ≠ {want}")

    # 9. 档案层无损：床位目录 36 张不动
    check(Bed.objects.count() == 36, f"床位目录应 36，实际 {Bed.objects.count()}")

    # 10. 评估剧本：张国栋 2 张已确认单各恰关联 1 条变更行；补录老人在待复评
    promo_as = Assessment.objects.filter(
        resident_id=PROMOTION_ID, status=Assessment.Status.CONFIRMED)
    check(promo_as.count() == 2,
          f"张国栋已确认评估单应 2 张，实际 {promo_as.count()}")
    for a in promo_as:
        linked = a.level_changes.count()
        check(linked == 1, f"评估单 {a.id} 应恰关联 1 条变更行，实际 {linked}")
    due = {row["resident"].name for row in review_lists()["due_review"]}
    check(stale_name in due, f"补录老人 {stale_name} 未出现在待复评（实际：{due or '空'}）")
    print("  全部通过 ✓")


if __name__ == "__main__":
    main()
