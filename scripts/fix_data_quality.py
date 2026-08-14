#!/usr/bin/env python3
"""修正 nursing-erp 演示数据质量：补空字段。

- 员工 phone / hire_date（全空 → 补真实感数据）
- 老人紧急联系人 contact_name / contact_phone（全空 → 补亲属信息）

幂等：只更新空值，不覆盖已有数据。
运行：cd nursing-erp && .venv/bin/python scripts/fix_data_quality.py
"""
import os
import sqlite3
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db.sqlite3")

# 常见亲属姓名池（用于老人紧急联系人）
CONTACT_NAMES = [
    "王丽华", "李建国", "张伟", "刘芳", "陈志强", "杨秀英", "赵永刚",
    "黄晓梅", "周建华", "吴桂芳", "徐文斌", "孙丽娟", "马国强", "朱慧敏",
    "胡志明", "郭雪梅", "何永平", "林婉婷", "罗建平", "高玉兰", "郑文杰",
    "梁秀云", "谢永强", "宋美玲", "唐志明", "许春燕", "韩立国", "冯丽萍",
    "曹建华", "彭秀珍", "邓永刚", "萧婉君", "傅国平", "沈玉华", "曾志强",
    "潘桂英",
]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. 员工 phone + hire_date
    rows = cur.execute(
        "SELECT id FROM staff_employee WHERE phone='' OR phone IS NULL OR hire_date IS NULL OR hire_date=''"
    ).fetchall()
    base = date(2018, 3, 1)
    n = 0
    for (emp_id,) in rows:
        phone = f"139{10000000 + emp_id:08d}"  # 139 + 8 位，共 11 位
        hire = base + timedelta(days=(emp_id * 97) % (365 * 7))  # 2018~2025 间分布
        cur.execute(
            "UPDATE staff_employee SET phone=?, hire_date=? WHERE id=?",
            (phone, hire.isoformat(), emp_id),
        )
        n += 1
    print(f"员工 phone/hire_date 补齐: {n} 人")

    # 2. 老人紧急联系人
    rows = cur.execute(
        "SELECT id FROM residents_resident WHERE contact_name='' OR contact_name IS NULL"
    ).fetchall()
    m = 0
    for (rid,) in rows:
        name = CONTACT_NAMES[(rid - 1) % len(CONTACT_NAMES)]
        phone = f"138{20000000 + rid:08d}"  # 138 + 8 位
        cur.execute(
            "UPDATE residents_resident SET contact_name=?, contact_phone=? WHERE id=?",
            (name, phone, rid),
        )
        m += 1
    print(f"老人紧急联系人补齐: {m} 人")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
