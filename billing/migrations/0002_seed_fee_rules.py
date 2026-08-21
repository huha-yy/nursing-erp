"""种子价目（Q3 演示默认值，用户拍板 2026-08-21）：
床位 800/月；护理 自理300/半护1200/全护2000/失智2400/月；餐费 15/餐。

get_or_create 幂等——admin 后续改价不会被重放覆盖（只在行不存在时插入）。
"""

from decimal import Decimal

from django.db import migrations

SEED = [
    ("bed", "", Decimal("800.00")),
    ("nursing", "自理", Decimal("300.00")),
    ("nursing", "半护", Decimal("1200.00")),
    ("nursing", "全护", Decimal("2000.00")),
    ("nursing", "失智", Decimal("2400.00")),
    ("meal", "", Decimal("15.00")),
]


def seed(apps, schema_editor):
    FeeRule = apps.get_model("billing", "FeeRule")
    for fee_type, key, amount in SEED:
        FeeRule.objects.get_or_create(
            fee_type=fee_type, key=key, defaults={"monthly_amount": amount}
        )


def unseed(apps, schema_editor):
    FeeRule = apps.get_model("billing", "FeeRule")
    for fee_type, key, _amount in SEED:
        FeeRule.objects.filter(fee_type=fee_type, key=key).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
