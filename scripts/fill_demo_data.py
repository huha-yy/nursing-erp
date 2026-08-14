#!/usr/bin/env python3
"""补全 nursing-erp 演示数据（空表/稀疏表）。

- 幂等：带 unique 约束的表用 update_or_create，其余按现有数量跳过已填部分。
- 与现有老人/员工/菜品/库存/点餐单数据自洽。

运行：
    cd nursing-erp && .venv/bin/python scripts/fill_demo_data.py
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nursing_erp.settings")

import django

django.setup()

from residents.models import Resident, HealthRecord, ResidentRoutine
from staff.models import Employee, Task
from operations.models import (
    InventoryItem,
    StockIn,
    StockOut,
    MaintenanceOrder,
    Inspection,
    Approval,
)
from meals.models import MealOrder, MealFinance, MealModificationLog

TODAY = date(2026, 8, 14)


def d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


def main() -> None:
    residents = list(Resident.objects.order_by("id"))
    employees = list(Employee.objects.order_by("id"))
    items = list(InventoryItem.objects.order_by("id"))
    orders = list(MealOrder.objects.order_by("id"))

    def resident(i: int) -> Resident:
        return residents[i % len(residents)]

    def employee(i: int) -> Employee:
        return employees[i % len(employees)]

    def item(i: int) -> InventoryItem:
        return items[i % len(items)]

    added = {}

    # ── 1. 入库记录 ──────────────────────────────────────────────
    if StockIn.objects.count() < 8:
        stockin = [
            (0, 100, "杭州康养供应链有限公司", d(6), "陈总务"),
            (1, 80, "杭州康养供应链有限公司", d(6), "陈总务"),
            (3, 500, "浙江医疗器械批发", d(5), "赵总务"),
            (5, 1000, "浙江医疗器械批发", d(5), "赵总务"),
            (6, 50, "洁达消毒用品", d(4), "陈总务"),
            (7, 300, "杭州康养供应链有限公司", d(3), "陈总务"),
            (10, 30, "杭州康养供应链有限公司", d(2), "赵总务"),
            (13, 50, "浙江医疗器械批发", d(1), "陈总务"),
        ]
        for idx, qty, supplier, dt, op in stockin:
            StockIn.objects.create(
                item=item(idx), quantity=qty, supplier=supplier, date=dt, operator=op
            )
        added["入库记录"] = len(stockin)

    # ── 2. 领用记录 ──────────────────────────────────────────────
    if StockOut.objects.count() < 8:
        stockout = [
            (0, 20, "张护士", d(5)),
            (3, 100, "李护士", d(5)),
            (5, 200, "王护士", d(4)),
            (6, 10, "陈总务", d(4)),
            (7, 50, "张护士", d(3)),
            (10, 5, "李护士", d(2)),
            (13, 10, "王护士", d(2)),
            (14, 30, "张护士", d(1)),
        ]
        for idx, qty, taker, dt in stockout:
            StockOut.objects.create(item=item(idx), quantity=qty, taken_by=taker, date=dt)
        added["领用记录"] = len(stockout)

    # ── 3. 餐费月结 ──────────────────────────────────────────────
    if MealFinance.objects.count() < 10:
        fin = 0
        for i in range(12):
            r = resident(i)
            total = 62 + (i * 7) % 30
            cancelled = (i * 3) % 6
            amount = Decimal(str((total - cancelled) * 15)) / Decimal("1")
            MealFinance.objects.update_or_create(
                resident=r,
                month="2026-08",
                defaults={
                    "total_meals": total,
                    "cancelled": cancelled,
                    "amount": Decimal(f"{amount:.2f}"),
                    "paid": i % 3 != 0,  # 2/3 已缴
                },
            )
            fin += 1
        added["餐费月结"] = fin

    # ── 4. 改退餐记录 ────────────────────────────────────────────
    if MealModificationLog.objects.count() < 6:
        mod = 0
        for i, order in enumerate(orders[:8]):
            MealModificationLog.objects.create(
                order=order,
                action="cancel" if i % 2 == 0 else "modify",
                reason=["临时有事外出", "口味不适改菜", "身体不适", "换餐至次日"][i % 4],
                changed_by=employee(i + 1).name,
            )
            mod += 1
        added["改退餐记录"] = mod

    # ── 5. 审批单 ────────────────────────────────────────────────
    if Approval.objects.count() < 6:
        approvals = [
            ("陈总务", "purchase", "采购尿不湿 L 码", "3 号楼尿不湿库存低于安全线，申请采购 200 包。", "approved"),
            ("赵总务", "purchase", "采购一次性口罩", "全院口罩库存告急，申请采购 2000 只。", "pending"),
            ("张护士", "leave", "张护士请假申请", "家中急事，申请 8 月 15 日请假一天。", "approved"),
            ("李护士", "leave", "李护士调休申请", "申请 8 月 16 日调休。", "pending"),
            ("王护士", "reimburse", "护理耗材费用报销", "3 号楼护理耗材采购垫付 860 元，申请报销。", "pending"),
            ("陈总务", "purchase", "采购消毒液", "全院清洁消毒用品补充采购。", "approved"),
            ("刘主任", "other", "楼栋消防演练计划", "拟于下周开展 1 号楼消防演练。", "pending"),
            ("张主任", "reimburse", "活动经费报销", "老人集体生日会活动经费 1200 元报销。", "approved"),
        ]
        for name, typ, title, content, status in approvals:
            Approval.objects.create(
                applicant_name=name, approval_type=typ, title=title,
                content=content, status=status,
            )
        added["审批单"] = len(approvals)

    # ── 6. 卫生巡检 ──────────────────────────────────────────────
    if Inspection.objects.count() < 6:
        inspections = [
            ("王建国", "1 号楼餐厅", d(1), "合格", "地面整洁，餐具消毒达标"),
            ("李卫东", "3 号楼公共区域", d(1), "合格", "走廊扶手已消毒"),
            ("王建国", "2 号楼卫生间", d(2), "不合格", "2 楼男卫地面有水渍，已通知保洁"),
            ("刘主任", "食堂后厨", d(2), "合格", "生熟分区规范"),
            ("吴主任", "1 号楼活动室", d(3), "合格", "通风良好"),
            ("李卫东", "3 号楼洗衣房", d(3), "不合格", "角落堆放杂物，已整改"),
            ("王建国", "2 号楼电梯", d(4), "合格", "轿厢清洁"),
            ("刘主任", "全院公共卫生间", d(5), "合格", "洗手液补充到位"),
        ]
        for name, area, dt, result, note in inspections:
            Inspection.objects.create(
                inspector_name=name, area=area, date=dt, result=result, note=note
            )
        added["卫生巡检"] = len(inspections)

    # ── 7. 报修工单 ──────────────────────────────────────────────
    if MaintenanceOrder.objects.count() < 6:
        repairs = [
            ("轮椅", "3 号楼 2 层", "轮椅左轮松动，推起来有异响", "张护士", "in_progress"),
            ("血压计", "护理站", "血压计读数不准，需要校准", "李护士", "pending"),
            ("热水器", "2 号楼淋浴间", "热水器不出热水", "王护士", "done"),
            ("电梯", "1 号楼", "电梯按键不灵敏", "刘主任", "pending"),
            ("制氧机", "3 号楼 3 层", "制氧机报警灯常亮", "张护士", "in_progress"),
            ("紫外线消毒灯", "医务室", "灯管老化需更换", "陈总务", "done"),
            ("呼叫器", "3 号楼 5 层", "呼叫器无响应", "李护士", "pending"),
            ("轮椅", "2 号楼 1 层", "轮椅刹车失灵", "王护士", "done"),
        ]
        for eq, loc, fault, by, status in repairs:
            MaintenanceOrder.objects.create(
                equipment_name=eq, location=loc, fault_description=fault,
                reported_by=by, status=status,
            )
        added["报修工单"] = len(repairs)

    # ── 8. 任务派发 ──────────────────────────────────────────────
    if Task.objects.count() < 6:
        tasks = [
            ("刘主任", 1, "护送老人体检", "护送 3 号楼 5 位老人到医务室体检", d(0), False),
            ("刘主任", 2, "3 号楼送餐", "午间为 3 号楼 3 层老人送餐", d(0), True),
            ("张主任", 3, "清洁消毒", "对 1 号楼公共区域进行消毒", d(1), True),
            ("刘主任", 4, "整理老人档案", "更新本周老人用药记录", d(2), False),
            ("吴主任", 5, "盘点库存", "盘点护理耗材库存并录入系统", d(1), True),
            ("刘主任", 6, "组织老人活动", "下午组织老人在活动室做手工", d(0), False),
            ("张主任", 7, "维修跟进", "跟进 3 号楼轮椅维修进度", d(3), True),
            ("吴主任", 8, "新员工带教", "带教新入职护理员熟悉流程", d(4), True),
        ]
        for assigner, emp_idx, title, content, deadline, done in tasks:
            Task.objects.create(
                assigner_name=assigner, assignee=employee(emp_idx),
                title=title, content=content, deadline=deadline, is_completed=done,
            )
        added["任务派发"] = len(tasks)

    # ── 9. 健康记录 ──────────────────────────────────────────────
    if HealthRecord.objects.count() < 10:
        records = []
        for i in range(12):
            r = resident(i)
            records.append(HealthRecord(
                resident=r, record_date=d(i % 5),
                blood_pressure=f"{118 + (i % 5) * 4}/{72 + (i % 3) * 3}",
                blood_sugar=Decimal(f"{4.8 + (i % 5) * 0.3:.1f}"),
                heart_rate=68 + (i % 7) * 2,
                weight=Decimal(f"{52.0 + (i % 9) * 1.5:.1f}"),
                temperature=Decimal(f"{36.4 + (i % 3) * 0.1:.1f}"),
                note="指标平稳" if i % 2 == 0 else "建议关注血压",
            ))
        HealthRecord.objects.bulk_create(records)
        added["健康记录"] = len(records)

    # ── 10. 作息记录 ──────────────────────────────────────────────
    if ResidentRoutine.objects.count() < 12:
        routines = []
        for i in range(15):
            r = resident(i)
            routines.append(ResidentRoutine(
                resident=r, log_date=d(i % 4),
                breakfast=i % 3 != 0,
                lunch=True,
                dinner=i % 5 != 0,
                activities=["散步", "打太极", "看电视", "做手工", "晒太阳"][i % 5],
                mood=["良好", "平稳", "愉悦", "一般"][i % 4],
            ))
        ResidentRoutine.objects.bulk_create(routines)
        added["作息记录"] = len(routines)

    print("=== 补数据完成 ===")
    for k, v in added.items():
        print(f"  {k}: +{v}")
    if not added:
        print("  （所有表已达标，未新增）")


if __name__ == "__main__":
    main()
