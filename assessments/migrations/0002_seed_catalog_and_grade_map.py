"""种子：国标 GB/T 42195-2022 的 26 个二级指标目录 + 等级→护理档映射（演示默认）。

分值口径（简化）：自理能力/基础运动能力各项 0-10，精神状态/感知觉与社会参与
各项 0-5 —— 原始满分 190，服务层归一化到 0-100（见 assessments/models.py docstring）。
映射不含「失智」：失智无法由分数推出，只能定级时人工改判（reason 必填）。
get_or_create 幂等——admin 后续调目录/改映射不会被重放覆盖。
"""

from django.db import migrations

# (一级指标, 二级指标, 分值上限, 展示顺序)
ITEMS = [
    ("自理能力", "进食", 10, 1), ("自理能力", "洗澡", 10, 2),
    ("自理能力", "修饰", 10, 3), ("自理能力", "穿衣", 10, 4),
    ("自理能力", "大便控制", 10, 5), ("自理能力", "小便控制", 10, 6),
    ("自理能力", "如厕", 10, 7), ("自理能力", "床椅转移", 10, 8),
    ("基础运动能力", "平地行走", 10, 9), ("基础运动能力", "上下楼梯", 10, 10),
    ("基础运动能力", "户外活动", 10, 11), ("基础运动能力", "卫生与安全", 10, 12),
    ("精神状态", "认知功能", 5, 13), ("精神状态", "攻击行为", 5, 14),
    ("精神状态", "抑郁症状", 5, 15), ("精神状态", "意识水平", 5, 16),
    ("精神状态", "视听力交流", 5, 17), ("精神状态", "配合评估", 5, 18),
    ("精神状态", "交往意愿", 5, 19), ("精神状态", "日常生活能力", 5, 20),
    ("精神状态", "兴趣爱好", 5, 21),
    ("感知觉与社会参与", "视力", 5, 22), ("感知觉与社会参与", "听力", 5, 23),
    ("感知觉与社会参与", "沟通能力", 5, 24), ("感知觉与社会参与", "社会交往", 5, 25),
    ("感知觉与社会参与", "社会活动", 5, 26),
]

# 能力等级 → 护理档（院内政策，后台可改；1级轻度受损仍以自理为主，边界机构自调）
GRADE_MAP = [(0, "自理"), (1, "自理"), (2, "半护"), (3, "全护"), (4, "全护")]


def seed(apps, schema_editor):
    item_model = apps.get_model("assessments", "AssessmentItem")
    for dimension, name, max_score, order in ITEMS:
        item_model.objects.get_or_create(
            dimension=dimension, name=name,
            defaults={"max_score": max_score, "order": order},
        )
    grade_map = apps.get_model("assessments", "GradeLevelMap")
    for grade, care_level in GRADE_MAP:
        grade_map.objects.get_or_create(grade=grade, defaults={"care_level": care_level})


def unseed(apps, schema_editor):
    item_model = apps.get_model("assessments", "AssessmentItem")
    item_model.objects.filter(
        dimension__in=[d for d, *_ in ITEMS], name__in=[n for _, n, *_ in ITEMS],
    ).delete()
    grade_map = apps.get_model("assessments", "GradeLevelMap")
    grade_map.objects.filter(grade__in=[g for g, _ in GRADE_MAP]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assessments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
