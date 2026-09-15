#!/usr/bin/env python3
"""演示数据重灌 — 保留档案底座，重置并重造「业务动态层」。

分层契约（2026-08-24 定）：
- 档案层不动：登录账号 / 员工 / 老人 / 床位 / 菜品库 / 价目表 / 库存目录 /
  家属账号与绑定（Q6 起属档案层，重灌只补种不清空）
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
    uv run python scripts/rebuild_demo_data.py --cover-until 2026-09-30   # 点餐/周菜单/排班前铺到 09-30
                                                              # （其余数据面保持过去式语义，不前铺）
    uv run python scripts/rebuild_demo_data.py --lang en        # P5 英文演示：人名/菜名/库存品名
                                                              # (含单位)/楼栋/楼层/自由文本英文化
                                                              # （枚举值不动；zh 重灌可逆回中文）
                                                              # ⚠ en 模式须同步跑 AI 侧
                                                              # seed_pg_demo_en.py --lang en
                                                              # （X-Building 权限链两边同值）
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
from beds.models import Bed, Building, Floor  # noqa: E402
from billing.models import FeeRule, MonthlyBill  # noqa: E402
from billing.services import arrears_stats, generate_month_bills, month_summary  # noqa: E402
from family.models import FamilyBinding, FamilyMember  # noqa: E402
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

# 固定口味画像 / 退改餐原因等自由文本模板移入 _T（P5 双语串表），经 T() 取用

DISH_RULES = [  # 菜品库纠偏（档案层既有 94 道菜几乎全标"素菜"）——按关键词重分类
    ("粥", "主食"), ("饭", "主食"), ("馒头", "主食"),
    ("花卷", "主食"), ("包子", "主食"), ("面条", "主食"),
    ("汤", "汤"), ("羹", "汤"),
    ("鱼", "荤菜"), ("鸡", "荤菜"), ("鸭", "荤菜"), ("肉", "荤菜"), ("虾", "荤菜"),
    ("排骨", "荤菜"), ("蛋", "荤菜"),
    ("拌", "小菜"), ("凉", "小菜"),
]


# ════════════════════════════════════════════════════════════════════
# P5 双语串表（2026-09-15 广交会英文演示）
#
# 拍板口径：数据英文化 = 人名/菜名/楼栋/楼层/自由文本内容英文；
# **枚举值不动**——护理等级（自理/半护/全护/失智）、餐次（早/午/晚）、
# 班次、科室、状态、菜品分类、巡检结果保持中文原值
# （UI 显示层 en 翻译目录已盖住）。
#
# 楼栋/楼层（P5b 2026-09-15 追加）：Building/Floor 台账 name 与
# Resident/Employee/Schedule 字符串缓存列随 overlay 改名。X-Building
# 权限链两边同步即保持匹配（dl-control 发 session.building → api_scope
# 查 Building 表）；AI 侧 PG nursing_users/nursing_residents/
# nursing_schedules 同值由 seed_pg_demo_en.py --lang en 同步 UPDATE。
#
# - 默认 zh 行为与旧版完全一致（每日 keepfresh cron 无感）
# - --lang en：档案层人名/菜名/库存品名+单位/楼栋/楼层按固定映射英文化
#   （overlay_archive，可逆——之后重跑 zh rebuild 即改回中文名）；
#   动态层自由文本串源切 en 表
# ════════════════════════════════════════════════════════════════════

def _parse_lang() -> str:
    if "--lang" in sys.argv:
        i = sys.argv.index("--lang")
        val = sys.argv[i + 1] if i + 1 < len(sys.argv) else "zh"
    else:
        val = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--lang=")), "zh")
    if val not in ("zh", "en"):
        raise SystemExit(f"✗ --lang 只支持 zh|en，收到 {val!r}")
    return val


LANG = _parse_lang()

# 人名 zh→en：老人 36 + 员工 41 + 家属联系人 36（唯一字符串；员工"刘主任"×2
# 同名同译）。en 模式 overlay 正向用，zh 模式反向改回——双向都必须一一对应。
NAME_ZH_EN = {
    # ── 老人（id 顺序）──
    "张国栋": "Zhang Guodong", "李秀兰": "Li Xiulan", "陈永发": "Chen Yongfa",
    "赵玉芬": "Zhao Yufen", "王淑珍": "Wang Shuzhen", "刘明德": "Liu Mingde",
    "吴桂英": "Wu Guiying", "周德胜": "Zhou Desheng", "黄美华": "Huang Meihua",
    "杨国华": "Yang Guohua", "徐秀英": "Xu Xiuying", "马德才": "Ma Decai",
    "沈桂花": "Shen Guihua", "朱长福": "Zhu Changfu", "许美玲": "Xu Meiling",
    "郑国平": "Zheng Guoping", "吕玉兰": "Lv Yulan", "何伟民": "He Weimin",
    "胡秀珍": "Hu Xiuzhen", "林德茂": "Lin Demao", "孙玉梅": "Sun Yumei",
    "高建平": "Gao Jianping", "郭秀英": "Guo Xiuying", "彭国栋": "Peng Guodong",
    "唐玉芬": "Tang Yufen", "宋长贵": "Song Changgui", "田桂花": "Tian Guihua",
    "范德明": "Fan Deming", "曹美凤": "Cao Meifeng", "廖永强": "Liao Yongqiang",
    "许桂兰": "Xu Guilan", "袁建华": "Yuan Jianhua", "邓秀珍": "Deng Xiuzhen",
    "苏国平": "Su Guoping", "万玉梅": "Wan Yumei", "石明远": "Shi Mingyuan",
    # ── 员工（角色名按角色译：护士/主任/组长/总务…）──
    "王建国": "Wang Jianguo", "张护士": "Nurse Zhang", "李护士": "Nurse Li",
    "王护士": "Nurse Wang", "陈总务": "Logistics Officer Chen",
    "赵总务": "Logistics Officer Zhao", "刘主任": "Director Liu",
    "张主任": "Director Zhang", "李卫东": "Li Weidong", "吴主任": "Director Wu",
    "周主任": "Director Zhou", "王组长": "Team Lead Wang",
    "陈组长": "Team Lead Chen", "赵小明": "Zhao Xiaoming",
    "孙组长": "Team Lead Sun", "钱小红": "Qian Xiaohong",
    "黄组长": "Team Lead Huang", "刘行政": "Admin Liu", "冯医务": "Medical Officer Feng",
    "孙财务": "Accountant Sun", "周安保": "Security Zhou",
    "李芳": "Li Fang", "王强": "Wang Qiang", "刘小梅": "Liu Xiaomei",
    "侯玉芬": "Hou Yufen", "陈建国": "Chen Jianguo", "张敏": "Zhang Min",
    "赵丽华": "Zhao Lihua", "孙志明": "Sun Zhiming", "周玉英": "Zhou Yuying",
    "吴秀丽": "Wu Xiuli", "郑文斌": "Zheng Wenbin", "杨桂兰": "Yang Guilan",
    "冯德才": "Feng Decai", "钱玉兰": "Qian Yulan", "韩立明": "Han Liming",
    "潘丽丽": "Pan Lili", "方永刚": "Fang Yonggang", "姚士杰": "Yao Shijie",
    "蒋秀兰": "Jiang Xiulan",
    # ── 家属联系人（紧急联系人，连带 FamilyMember.name / User.first_name）──
    "王丽华": "Wang Lihua", "李建国": "Li Jianguo", "张伟": "Zhang Wei",
    "刘芳": "Liu Fang", "陈志强": "Chen Zhiqiang", "杨秀英": "Yang Xiuying",
    "赵永刚": "Zhao Yonggang", "黄晓梅": "Huang Xiaomei", "周建华": "Zhou Jianhua",
    "吴桂芳": "Wu Guifang", "徐文斌": "Xu Wenbin", "孙丽娟": "Sun Lijuan",
    "马国强": "Ma Guoqiang", "朱慧敏": "Zhu Huimin", "胡志明": "Hu Zhiming",
    "郭雪梅": "Guo Xuemei", "何永平": "He Yongping", "林婉婷": "Lin Wanting",
    "罗建平": "Luo Jianping", "高玉兰": "Gao Yulan", "郑文杰": "Zheng Wenjie",
    "梁秀云": "Liang Xiuyun", "谢永强": "Xie Yongqiang", "宋美玲": "Song Meiling",
    "唐志明": "Tang Zhiming", "许春燕": "Xu Chunyan", "韩立国": "Han Liguo",
    "冯丽萍": "Feng Liping", "曹建华": "Cao Jianhua", "彭秀珍": "Peng Xiuzhen",
    "邓永刚": "Deng Yonggang", "萧婉君": "Xiao Wanjun", "傅国平": "Fu Guoping",
    "沈玉华": "Shen Yuhua", "曾志强": "Zeng Zhiqiang", "潘桂英": "Pan Guiying",
}
assert len(NAME_ZH_EN) == len(set(NAME_ZH_EN.values())), "NAME_ZH_EN en 值有重复，反向映射不可逆"

# 菜名 zh→en（档案层 94 道；分类/价格/可用性等其余字段不动）
DISH_ZH_EN = {
    "丝瓜汤": "Sponge Gourd Soup", "八宝粥": "Eight-Treasure Porridge",
    "冬瓜排骨": "Winter Melon with Ribs", "冬瓜汤": "Winter Melon Soup",
    "凉拌木耳": "Black Fungus Salad", "凉拌菠菜": "Spinach Salad",
    "凉拌黄瓜": "Cucumber Salad", "南瓜粥": "Pumpkin Porridge",
    "卤蛋": "Marinated Egg", "土豆炖鸡": "Chicken Stew with Potatoes",
    "小米粥": "Millet Porridge", "小米饭": "Millet Rice",
    "山药汤": "Chinese Yam Soup", "拌三丝": "Three-Shred Salad",
    "拌海带": "Kelp Salad", "拌莴笋丝": "Celtuce Salad",
    "木耳炒蛋": "Egg with Black Fungus", "杂粮饭": "Mixed Grain Rice",
    "清炒油麦菜": "Stir-Fried Leaf Lettuce", "清炒生菜": "Stir-Fried Lettuce",
    "清炒芦笋": "Stir-Fried Asparagus", "清炒西蓝花": "Stir-Fried Broccoli",
    "清炖羊肉": "Clear-Stewed Lamb", "清蒸鲈鱼": "Steamed Sea Bass",
    "炒南瓜": "Stir-Fried Pumpkin", "炒空心菜": "Stir-Fried Water Spinach",
    "炒胡萝卜丝": "Stir-Fried Carrot Strips", "炒花菜": "Stir-Fried Cauliflower",
    "炒豆苗": "Stir-Fried Pea Sprouts", "炒青菜": "Stir-Fried Greens",
    "炖牛肉": "Stewed Beef", "煎蛋": "Fried Egg", "煮蛋": "Hard-Boiled Egg",
    "燕麦粥": "Oatmeal Porridge", "牛奶": "Milk",
    "玉米馒头": "Corn Steamed Bun", "番茄汤": "Tomato Soup",
    "白切鸡": "Poached Chicken", "白煮蛋": "Boiled Egg", "米饭": "Steamed Rice",
    "粉丝蒸虾": "Steamed Shrimp with Glass Noodles", "糖醋鱼片": "Sweet & Sour Fish",
    "素包子": "Vegetable Bun", "素炒秋葵": "Stir-Fried Okra",
    "素炒茄子": "Stir-Fried Eggplant", "紫菜汤": "Seaweed Soup",
    "紫薯包": "Purple Sweet Potato Bun", "红枣发糕": "Jujube Steamed Cake",
    "红枣汤": "Jujube Soup", "红烧带鱼": "Braised Ribbonfish",
    "红烧排骨": "Braised Spareribs", "红烧狮子头": "Braised Lion's Head Meatballs",
    "红豆汤": "Red Bean Soup", "红豆浆": "Red Bean Soy Milk",
    "红豆薏米粥": "Red Bean & Job's Tears Porridge", "绿豆汤": "Mung Bean Soup",
    "肉末蒸蛋": "Steamed Egg with Minced Pork", "花卷": "Steamed Twisted Roll",
    "芹菜花生": "Celery with Peanuts", "茶叶蛋": "Tea Egg",
    "莲子汤": "Lotus Seed Soup", "菌菇汤": "Mushroom Soup",
    "葱油鲳鱼": "Pomfret with Scallion Oil", "葱花卷": "Scallion Twisted Roll",
    "蒜蓉菠菜": "Garlic Spinach", "蒸山药": "Steamed Chinese Yam",
    "蒸玉米": "Steamed Corn", "蒸红薯": "Steamed Sweet Potato",
    "蒸芋头": "Steamed Taro", "蒸蛋": "Steamed Egg",
    "蒸蛋羹": "Steamed Egg Custard", "蒸饺": "Steamed Dumplings",
    "薏米汤": "Job's Tears Soup", "薏米粥": "Job's Tears Porridge",
    "虾仁豆腐": "Tofu with Shrimp", "蛋花汤": "Egg Drop Soup",
    "西红柿炒蛋": "Scrambled Egg with Tomato", "西芹百合": "Celery with Lily Bulbs",
    "豆沙包": "Red Bean Paste Bun", "豆浆": "Soy Milk", "豆腐汤": "Tofu Soup",
    "酸奶": "Yogurt", "银耳汤": "Snow Fungus Soup",
    "韭菜炒蛋": "Egg with Chives", "馒头": "Steamed Bun",
    "香菇炖鸡": "Chicken Stew with Shiitake", "香菇青菜": "Greens with Shiitake",
    "鱼香肉丝": "Yu-Xiang Shredded Pork", "鸡蛋": "Egg", "鹌鹑蛋": "Quail Egg",
    "麻婆豆腐": "Mapo Tofu", "黄焖鸡": "Braised Chicken",
    "黑米粥": "Black Rice Porridge", "米粥": "Rice Porridge",
}
assert len(DISH_ZH_EN) == len(set(DISH_ZH_EN.values())), "DISH_ZH_EN en 值有重复"

# 库存品名 zh→en（档案层 InventoryItem 15 项，2026-09-15 从生产库快照逐个译；
# 分类/数量/安全库存不动，低库存面板/库存页 en 演示不再露中文品名）
INV_ZH_EN = {
    "尿不湿L码": "Adult Diapers L", "尿不湿M码": "Adult Diapers M",
    "尿不湿S码": "Adult Diapers S", "一次性手套": "Disposable Gloves",
    "胃管": "Feeding Tubes", "口罩": "Surgical Masks",
    "消毒液": "Disinfectant", "护理垫": "Underpads",
    "轮椅": "Wheelchairs", "血压计": "BP Monitors",
    "血糖试纸": "Blood Glucose Test Strips", "一次性注射器": "Disposable Syringes",
    "吸痰管": "Suction Catheters", "医用胶带": "Medical Tape",
    "纸尿裤": "Disposable Diapers",
}
assert len(INV_ZH_EN) == len(set(INV_ZH_EN.values())), "INV_ZH_EN en 值有重复，反向映射不可逆"

# 库存单位 zh→en（InventoryItem.unit 数据列；en 值互异保证 zh 反向可逆——
# "只"/"支" 不能都译 pcs，否则回译会并到同一个 zh）
UNIT_ZH_EN = {
    "包": "pack", "只": "pcs", "根": "tube", "瓶": "bottle",
    "片": "pad", "台": "unit", "盒": "box", "支": "each",
    "卷": "roll", "箱": "case", "套": "set",
}
assert len(UNIT_ZH_EN) == len(set(UNIT_ZH_EN.values())), "UNIT_ZH_EN en 值有重复，反向映射不可逆"

# 楼栋 zh→en（P5b 2026-09-15）：Building.name 台账锚点 + Resident/Employee/
# Schedule 字符串缓存列 + AI 侧 PG（nursing_users/nursing_residents/
# nursing_schedules，seed_pg_demo_en.py 同步 UPDATE）——X-Building 权限链
# 两边同值才不断。一对一映射，zh 重灌反向回译。
BUILDING_ZH_EN = {f"{i}号楼": f"Building {i}" for i in range(1, 7)}
assert len(set(BUILDING_ZH_EN.values())) == len(BUILDING_ZH_EN), \
    "BUILDING_ZH_EN en 值有重复，反向映射不可逆"

# 楼层 zh→en（Floor.name + Resident/Schedule 缓存列；生产值仅 1层/2层，
# "3层" 为自由文本兜底位）。en 值互异保证 zh 反向可逆。
FLOOR_ZH_EN = {"1层": "Floor 1", "2层": "Floor 2", "3层": "Floor 3"}
assert len(set(FLOOR_ZH_EN.values())) == len(FLOOR_ZH_EN), \
    "FLOOR_ZH_EN en 值有重复，反向映射不可逆"


def tr(text: str) -> str:
    """人名逐串翻译（en 模式命中串表才替换；zh 原样返回）。"""
    return NAME_ZH_EN.get(text, text) if LANG == "en" else text


def overlay_archive() -> None:
    """档案层双语覆盖（可逆）：只改名字段，其余字段一律不动。

    en：Resident.name / Employee.name / Dish.name / Resident.contact_name
        / InventoryItem.name+unit 英文化（家属侧 FamilyMember.name 与登录
        User.first_name 按手机号连带同步——家属端看到的人名跟老人档案保持
        同语言；库存分类/数量/安全库存不动，出入库记录走外键无冗余品名）；
        楼栋/楼层（P5b）：Building/Floor 台账 name + Resident/Employee
        字符串缓存列改名（Schedule/巡检区域等动态层重造时直接写新值，
        此处无行可改）。X-Building 权限链要求 AI 侧 PG 同步——en 重灌后
        必须跑 seed_pg_demo_en.py --lang en（AI 仓库），否则 dl-control
        楼长发头查无此名直接 400。
    zh：en→zh 反向改回——英文演示后重跑 zh rebuild 名字复原（cron 无感）。
    房间号/出生年月/护理等级/菜品分类等全部不动。
    """
    name_map = NAME_ZH_EN if LANG == "en" else {v: k for k, v in NAME_ZH_EN.items()}
    dish_map = DISH_ZH_EN if LANG == "en" else {v: k for k, v in DISH_ZH_EN.items()}
    inv_map = INV_ZH_EN if LANG == "en" else {v: k for k, v in INV_ZH_EN.items()}
    unit_map = UNIT_ZH_EN if LANG == "en" else {v: k for k, v in UNIT_ZH_EN.items()}
    bld_map = BUILDING_ZH_EN if LANG == "en" else {v: k for k, v in BUILDING_ZH_EN.items()}
    flr_map = FLOOR_ZH_EN if LANG == "en" else {v: k for k, v in FLOOR_ZH_EN.items()}
    n_r = n_e = n_d = n_f = n_i = n_b = 0
    for r in Resident.objects.order_by("id"):
        new = name_map.get(r.name, r.name)
        contact = name_map.get(r.contact_name, r.contact_name) if r.contact_name else r.contact_name
        if new != r.name or contact != r.contact_name:
            r.name, r.contact_name = new, contact
            r.save(update_fields=["name", "contact_name"])
            n_r += 1
        if r.contact_phone:
            fam = FamilyMember.objects.filter(phone=r.contact_phone).first()
            if fam and fam.name != contact and contact:
                fam.name = contact
                fam.save(update_fields=["name"])
                n_f += 1
            User.objects.filter(username=r.contact_phone).update(first_name=contact)
    for e in Employee.objects.order_by("id"):
        new = name_map.get(e.name, e.name)
        if new != e.name:
            e.name = new
            e.save(update_fields=["name"])
            n_e += 1
    for d in Dish.objects.order_by("id"):
        new = dish_map.get(d.name, d.name)
        if new != d.name:
            d.name = new
            d.save(update_fields=["name"])
            n_d += 1
    for it in InventoryItem.objects.order_by("id"):
        new = inv_map.get(it.name, it.name)
        unit = unit_map.get(it.unit, it.unit)
        if new != it.name or unit != it.unit:
            it.name, it.unit = new, unit
            it.save(update_fields=["name", "unit"])
            n_i += 1
    # 楼栋/楼层改名：台账 name + 字符串缓存列同表同值（一对一映射，UPDATE
    # 逐值切换无唯一冲突）。Room.number/Bed 不动；Schedule 是动态层，重造时
    # 自然写新值。漏改列会被 run_assertions 的台账一致性断言暴露。
    n_b += sum(
        Building.objects.filter(name=zh).update(name=en)
        for zh, en in bld_map.items()
    )
    n_b += sum(
        Floor.objects.filter(name=zh).update(name=en)
        for zh, en in flr_map.items()
    )
    for zh, en in bld_map.items():
        n_b += Resident.objects.filter(building=zh).update(building=en)
        n_b += Employee.objects.filter(building=zh).update(building=en)
    for zh, en in flr_map.items():
        n_b += Resident.objects.filter(floor=zh).update(floor=en)
    tag = "英文化" if LANG == "en" else "回译中文"
    print(f"  档案层{tag}：老人(含联系人) {n_r} / 员工 {n_e} / 菜品 {n_d} /"
          f" 库存(含单位) {n_i} / 家属账号 {n_f} / 楼栋楼层 {n_b}")


# 自由文本模板（动态层）：zh 键与旧版字面量一致；en 为对译
_T = {
    "zh": {
        "standing_requests": {7: "糖尿病餐", 19: "软食", 2: "少盐", 23: "少油"},
        "occasional": ["少油", "软一点", "趁热", "分量少一些"],
        "cancel_weekday": ["身体不适没胃口", "不爱吃当天的菜", "体检需要空腹", "牙口不好吃不了"],
        "cancel_weekend": ["家属接出去吃了", "回家过周末", "家属探视带了饭"],
        "modify_reasons": ["老人要求换菜", "牙口不好换软食", "同菜吃腻了换口味"],
        "mod_fmt": "原: {old} → 新: {new} ({reason})",
        "timeline_rows": [
            (2, -2, 15, "半护", 55, "术后康复期，需协助起居", "张主任"),
            (PROMOTION_ID, -1, 1, "半护", 55, "行动能力下降，需部分生活协助", "刘主任"),
            (PROMOTION_ID, 0, 1, "全护", 75, "病情加重，需全天照护", "刘主任"),
        ],
        "couple": ("张国栋", "李秀兰"),
        "discharge_reason": "因病离世",
        "transfer_reason": "随护理等级由半护转全护，迁入介护区",
        "log_details": ["情况平稳，按护理计划执行。", "进食正常，餐后协助漱口。",
                        "协助如厕一次，无异常。", "按时翻身，皮肤完好。",
                        "生命体征测量正常并记录。"],
        "note_stable": "指标平稳",
        "note_high": "血压偏高，持续关注",
        "activities": ["散步", "打太极", "看电视", "做手工", "晒太阳"],
        "moods": ["良好", "平稳", "愉悦", "一般"],
        "meds": [("苯磺酸氨氯地平片", "5mg", "qd"), ("二甲双胍缓释片", "0.5g", "bid"),
                 ("阿托伐他汀钙片", "20mg", "qd"), ("硝酸甘油片", "0.5mg", "prn"),
                 ("奥美拉唑肠溶胶囊", "20mg", "qd"), ("复方丹参滴丸", "10丸", "tid"),
                 ("格列美脲片", "2mg", "qd"), ("氢氯噻嗪片", "25mg", "qd")],
        "med_stop_note": "疗程结束停用",
        "task_seed": [
            ("护送老人体检", "护送本楼 5 位老人到医务室体检", -1, True),
            ("楼栋送餐", "午间为 3 层老人送餐", 0, True),
            ("公共区域消毒", "对本楼公共区域进行消毒", -2, True),
            ("整理老人档案", "更新本周老人用药记录", 1, False),
            ("库存盘点", "盘点护理耗材库存并录入系统", 0, True),
            ("组织老人活动", "下午组织老人在活动室做手工", 0, False),
            ("维修跟进", "跟进本楼轮椅维修进度", -3, True),
            ("新员工带教", "带教新入职护理员熟悉流程", 2, False),
        ],
        "sched_night": "夜间巡房两次",
        "sched_day": "协助老人午晚餐",
        "perf_comment": "工作认真负责",
        "suppliers": ["杭州康养供应链有限公司", "浙江医疗器械批发", "洁达消毒用品"],
        "approvals": [
            ("陈总务", "purchase", "采购尿不湿L码",
             "尿不湿L码库存低于安全线，申请采购 200 包。", "pending"),
            ("赵总务", "purchase", "采购一次性口罩",
             "全院口罩库存告急，申请采购 2000 只。", "pending"),
            ("张护士", "leave", "张护士请假申请", "家中急事，申请下周三请假一天。", "approved"),
            ("李护士", "leave", "李护士调休申请", "申请下周五调休。", "pending"),
            ("王护士", "reimburse", "护理耗材费用报销",
             "3号楼护理耗材采购垫付 860 元，申请报销。", "pending"),
            ("陈总务", "purchase", "采购消毒液", "全院清洁消毒用品补充采购。", "approved"),
        ],
        "inspections": [
            ("王建国", "1号楼餐厅", -1, "合格", "地面整洁，餐具消毒达标"),
            ("李卫东", "3号楼公共区域", -1, "合格", "走廊扶手已消毒"),
            ("王建国", "2号楼卫生间", -2, "不合格", "2楼男卫地面有水渍，已通知保洁"),
            ("刘主任", "食堂后厨", -2, "合格", "生熟分区规范"),
            ("吴主任", "1号楼活动室", -3, "合格", "通风良好"),
            ("李卫东", "3号楼洗衣房", -3, "不合格", "角落堆放杂物，已整改"),
        ],
        "maintenance": [
            ("轮椅", "3号楼2层", "轮椅左轮松动，推起来有异响", "张护士", "in_progress"),
            ("血压计", "护理站", "血压计读数不准，需要校准", "李护士", "pending"),
            ("热水器", "2号楼淋浴间", "热水器不出热水", "王护士", "done"),
            ("电梯", "1号楼", "电梯按键不灵敏", "刘主任", "pending"),
            ("制氧机", "3号楼3层", "制氧机报警灯常亮", "张护士", "in_progress"),
            ("呼叫器", "5号楼2层", "呼叫器无响应", "钱小红", "pending"),
        ],
    },
    "en": {
        "standing_requests": {7: "Diabetic meal", 19: "Soft diet", 2: "Low salt", 23: "Low oil"},
        "occasional": ["Less oil", "Softer food", "Serve while hot", "Smaller portion"],
        "cancel_weekday": ["Feeling unwell, no appetite", "Doesn't like today's dishes",
                           "Needs an empty stomach for a checkup", "Bad teeth, can't chew it"],
        "cancel_weekend": ["Family took them out for a meal", "Home for the weekend",
                           "Family brought food on a visit"],
        "modify_reasons": ["Resident asked for a change", "Switched to soft food for bad teeth",
                           "Tired of the same dish"],
        "mod_fmt": "old: {old} → new: {new} ({reason})",
        "timeline_rows": [
            (2, -2, 15, "半护", 55, "Post-op recovery; needs help with daily living", "Director Zhang"),
            (PROMOTION_ID, -1, 1, "半护", 55,
             "Declining mobility; needs partial living assistance", "Director Liu"),
            (PROMOTION_ID, 0, 1, "全护", 75,
             "Condition worsened; needs full-day care", "Director Liu"),
        ],
        "couple": ("Zhang Guodong", "Li Xiulan"),
        "discharge_reason": "Passed away due to illness",
        "transfer_reason": "Moved to the skilled-care zone after care level changed from semi-care to full care",
        "log_details": ["Stable; care plan carried out as usual.",
                        "Ate normally; assisted with mouth rinse after the meal.",
                        "Assisted with toileting once; nothing unusual.",
                        "Turned on schedule; skin intact.",
                        "Vital signs measured and recorded; all normal."],
        "note_stable": "Vitals stable",
        "note_high": "BP slightly high; monitoring",
        "activities": ["Walking", "Tai Chi", "Watching TV", "Handcrafts", "Sunbathing"],
        "moods": ["Good", "Calm", "Cheerful", "Average"],
        "meds": [("Amlodipine Besylate", "5mg", "qd"), ("Metformin XR", "0.5g", "bid"),
                 ("Atorvastatin", "20mg", "qd"), ("Nitroglycerin", "0.5mg", "prn"),
                 ("Omeprazole", "20mg", "qd"), ("Compound Danshen Pills", "10 pills", "tid"),
                 ("Glimepiride", "2mg", "qd"), ("Hydrochlorothiazide", "25mg", "qd")],
        "med_stop_note": "Course completed; discontinued",
        "task_seed": [
            ("Escort residents to checkups", "Escort 5 residents to the clinic for checkups", -1, True),
            ("Building meal delivery", "Deliver lunch to residents on floor 3", 0, True),
            ("Common-area disinfection", "Disinfect common areas of the building", -2, True),
            ("Update resident files", "Update this week's medication records", 1, False),
            ("Inventory count", "Count nursing supplies and enter into the system", 0, True),
            ("Organize resident activities", "Handcraft session in the activity room this afternoon", 0, False),
            ("Repair follow-up", "Follow up on the wheelchair repair", -3, True),
            ("New-staff mentoring", "Mentor the new caregiver on routines", 2, False),
        ],
        "sched_night": "Two night rounds",
        "sched_day": "Assist with lunch and dinner",
        "perf_comment": "Conscientious and dedicated",
        "suppliers": ["Hangzhou Kangyang Supply Chain Co.",
                      "Zhejiang Medical Devices Wholesale", "Jieda Disinfection Products"],
        "approvals": [
            ("陈总务", "purchase", "Purchase diapers (size L)",
             "Diaper (L) stock is below the safety line; requesting 200 packs.", "pending"),
            ("赵总务", "purchase", "Purchase disposable masks",
             "Facility-wide mask stock is running low; requesting 2000 masks.", "pending"),
            ("张护士", "leave", "Nurse Zhang leave request",
             "Family emergency; requesting one day off next Wednesday.", "approved"),
            ("李护士", "leave", "Nurse Li compensatory leave",
             "Requesting compensatory leave next Friday.", "pending"),
            ("王护士", "reimburse", "Nursing supplies reimbursement",
             "Paid 860 yuan out of pocket for Bldg 3 nursing supplies; requesting reimbursement.", "pending"),
            ("陈总务", "purchase", "Purchase disinfectant",
             "Facility-wide cleaning & disinfection supplies replenishment.", "approved"),
        ],
        "inspections": [
            ("王建国", "Bldg 1 Dining Hall", -1, "合格", "Floor clean; tableware disinfection up to standard"),
            ("李卫东", "Bldg 3 Common Area", -1, "合格", "Corridor handrails disinfected"),
            ("王建国", "Bldg 2 Restroom", -2, "不合格", "Water on the men's restroom floor; cleaning notified"),
            ("刘主任", "Main Kitchen", -2, "合格", "Raw/cooked separation up to standard"),
            ("吴主任", "Bldg 1 Activity Room", -3, "合格", "Well ventilated"),
            ("李卫东", "Bldg 3 Laundry Room", -3, "不合格", "Clutter in the corner; rectified"),
        ],
        "maintenance": [
            ("Wheelchair", "Bldg 3 Floor 2", "Left wheel of the wheelchair is loose and rattles", "张护士", "in_progress"),
            ("BP Monitor", "Nursing Station", "BP monitor readings inaccurate; needs calibration", "李护士", "pending"),
            ("Water Heater", "Bldg 2 Shower Room", "Water heater produces no hot water", "王护士", "done"),
            ("Elevator", "Bldg 1", "Elevator buttons not responsive", "刘主任", "pending"),
            ("Oxygen Concentrator", "Bldg 3 Floor 3", "Oxygen concentrator alarm light stays on", "张护士", "in_progress"),
            ("Call Bell", "Bldg 5 Floor 2", "Call bell has no response", "钱小红", "pending"),
        ],
    },
}


def T(key: str):
    """当前语言的自由文本模板（动态层串源统一走这里）。"""
    return _T[LANG][key]


# 异常剧本 en 描述（与 INCIDENT_BASE/EXTRA 逐行对齐，仅第 4 列文本不同；
# 结构列——老人id/类别/严重度/时序/处理——复制 zh 行，杜绝漂移）
INCIDENT_BASE_EN = [
    "Refused lunch; coaxed patiently by the caregiver and ate a small amount",
    "Slipped and fell in the corridor; sent for hospital examination, no fracture",
    "Feeling low from missing family; arranged a video call with relatives",
    "Redness over the sacral area; pressure-relief care started",
    "Ate little at breakfast; under continued observation",
    "Wandering the corridor looking for an exit; guided back to the room",
]
INCIDENT_EXTRA_EN = [
    "Slipped in the bathroom during a night toileting trip, landed on the right hip; "
    "conscious with localized pain. Ice pack applied, movement restricted, family "
    "contacted for an outside X-ray",
    "Repeatedly wandered to the floor exit after dinner trying to go out; remained "
    "restless after being led back. Night rounds increased",
    "Sacral skin break about 2x2 cm (stage II); reported to the head nurse, "
    "pressure-relief mattress replaced and scheduled turning in place",
    "Morning BP 182/104 mmHg with dizziness; repeat still high. Extra medication "
    "given per doctor's orders, continuous monitoring",
    "Irritable in the afternoon and unwilling to join group activities; relieved "
    "after a walk and chat with a caregiver",
    "Ate about half of lunch, complained the food was too salty; kitchen notified "
    "to adjust the seasoning",
    "Morning chest tightness and shortness of breath, SpO2 88%; transferred to the "
    "district hospital at once, diagnosed with acute-on-chronic heart failure, "
    "returned after treatment and now stable",
    "Stumbled off balance at the end of rehab training without falling; minor "
    "abrasion on the right knee, cleaned and bandaged",
    "Reported palpitations at night with HR 102 bpm; re-measured 88 bpm after 30 "
    "minutes of bed rest, kept under observation",
    "Ate less than a third of two consecutive meals, 1.5 kg weight loss vs last "
    "month; swallowing assessment scheduled",
    "Loitered in the Building 5 lobby trying to go out in the afternoon; led back "
    "after the face-recognition access alert, family informed by phone",
    "Heel redness without skin break (stage I); pressure-relief boots on and q2h "
    "turning in place",
    "Slipped on the wet floor at the bathroom entrance but grabbed the handrail "
    "without falling; non-slip mats added and warning signs posted",
    "Noon blood glucose 8.9 mmol/L, on the high side; advised to cut sweets, "
    "re-tested 7.2 before dinner",
    "Withdrawn and low after the roommate was discharged; improved after two "
    "social-worker companion visits",
    "Disoriented at dusk insisting on going home; calmed and guided back, mood "
    "stabilized",
    "Low mood after the family cancelled the visit; settled after a video call "
    "that evening",
    "Scratch marks on the left forearm (self-scratching); nails trimmed and "
    "anti-itch ointment applied",
    "Poor appetite at dinner; appetite back to normal at next morning's breakfast",
]


def incident_rows() -> list[tuple]:
    """当前语言的异常剧本（BASE+EXTRA）。en 模式仅替换描述文本（元组第 4 列）。"""
    base, extra = INCIDENT_BASE, INCIDENT_EXTRA
    if LANG == "en":
        assert len(INCIDENT_BASE_EN) == len(INCIDENT_BASE), "BASE en 描述行数与 zh 不齐"
        assert len(INCIDENT_EXTRA_EN) == len(INCIDENT_EXTRA), "EXTRA en 描述行数与 zh 不齐"
        base = [r[:3] + (d,) + r[4:] for r, d in zip(INCIDENT_BASE, INCIDENT_BASE_EN)]
        extra = [r[:3] + (d,) + r[4:] for r, d in zip(INCIDENT_EXTRA, INCIDENT_EXTRA_EN)]
    return base + extra


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
    P5：原因/经办人文本取自 _T[LANG]（en 模式主任名与英文描述，档位值仍中文枚举）。
    """
    return [
        (rid, (shift_month(anchor, moff) if moff else anchor).replace(day=day),
         to_l, target, reason, op)
        for rid, moff, day, to_l, target, reason, op in T("timeline_rows")
    ]


def pool_pick(pools: dict, cat: str, rot: int, k: int, avoid: set | None = None) -> list:
    """从分类池确定性取 k 道（轮转抽样）；池空则退回素菜池。
    avoid：命中时顺位下移——改餐换入菜不得与本单已有菜重复，否则撞
    meals_mealorder_dishes 的 (order, dish) 唯一约束（2026-09-03 锚 09-03 时炸出）。"""
    pool = pools.get(cat) or pools.get("素菜") or []
    avoid = avoid or set()
    picks: list = []
    for i in range(len(pool)):
        cand = pool[(rot + i) % len(pool)][0]
        if cand in avoid or cand in picks:
            continue
        picks.append(cand)
        if len(picks) >= k:
            break
    return picks


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


def seed_family() -> None:
    """家属账号种子（Q6）——档案层语义：幂等、可重复重灌、绝不重建已有账号。

    口径：
    - 每位在住老人按 contact_name/contact_phone 建一个"子女"账号（密码 123456，
      仅建号时设置；之后用户改密不覆盖——忘了走 admin「重置密码」action）
    - username（=手机号）被员工或其他账号占用 → 跳过并告警（不抢号）
    - 剧情加成：1号楼101 同房两老共用一个子女账号（多绑演示：一位家属看两位老人）
    """
    created = existed = skipped = 0
    bindings_created = 0
    for r in Resident.objects.order_by("id"):
        if not (r.contact_name and r.contact_phone):
            continue
        fm = FamilyMember.objects.filter(phone=r.contact_phone).first()
        if fm is None:
            if User.objects.filter(username=r.contact_phone).exists():
                print(f"    跳过 {r.name}：手机号 {r.contact_phone} 已被非家属账号占用")
                skipped += 1
                continue
            user = User.objects.create_user(
                username=r.contact_phone, password="123456", first_name=r.contact_name,
            )
            fm = FamilyMember.objects.create(user=user, name=r.contact_name, phone=r.contact_phone)
            created += 1
        else:
            existed += 1
        _, made = FamilyBinding.objects.get_or_create(
            family=fm, resident=r, defaults={"relation": FamilyBinding.Relation.CHILD}
        )
        bindings_created += int(made)

    # 多绑演示：张国栋(101)与李秀兰(102)是老两口，子女王丽华一个账号看两位老人
    # （库内房间为单人间，"同房两老"不成立，剧情改为同院不同房）
    # P5：en 模式档案已英文化，名字按当前语言查（张/李 → Zhang/Li）
    couple = list(Resident.objects.filter(name__in=T("couple")).order_by("id"))
    if len(couple) == 2:
        fm1 = FamilyMember.objects.filter(phone=couple[0].contact_phone).first()
        if fm1 is not None:
            _, made = FamilyBinding.objects.get_or_create(
                family=fm1, resident=couple[1], defaults={"relation": FamilyBinding.Relation.CHILD}
            )
            bindings_created += int(made)

    print(f"  家属账号：新建 {created} / 已有 {existed} / 跳过 {skipped}；"
          f"绑定新增 {bindings_created}（张国栋+李秀兰 一个子女账号双绑就位）")


def main() -> None:
    if LANG == "en":
        print("⚠ 演示英文模式（--lang en）：档案层人名/菜名/楼栋/楼层与动态层自由文本"
              "将英文化；枚举值（护理等级/餐次/班次/菜品分类/巡检结果）保持中文原值，"
              "UI 由 en 翻译目录盖住。楼栋改名后 X-Building 权限链要求 AI 侧同步："
              "必须跑 seed_pg_demo_en.py --lang en（AI 仓库）。恢复中文=重跑默认 zh 重灌。")

    # 外科手术模式：只补种家属账号（Q6 上线用）——纯增量 INSERT，不动动态层，
    # 与常驻 runserver 并行安全，故不进 runserver 守卫
    if "--seed-family-only" in sys.argv:
        with transaction.atomic():
            seed_family()
        return

    # 外科手术模式：只补种告警演示数据（2026-08-25，告警页主从改造后加密度）
    # ——纯增量 INSERT，不动其他域，与常驻 runserver 并行安全。幂等：库中
    # 已超出 BASE 数量即视为补过，直接跳过（全量重灌走 gen_other_domains）
    if "--seed-incidents-extra" in sys.argv:
        if IncidentReport.objects.count() > len(INCIDENT_BASE):
            print(f"✓ 告警演示数据已补过（现有 {IncidentReport.objects.count()} 条），跳过")
            return
        residents = list(Resident.objects.order_by("id"))
        employees = list(Employee.objects.order_by("id"))
        cgs_by_building: dict[str, list[Employee]] = {}
        for e in employees:
            if e.is_caregiver and e.building:
                cgs_by_building.setdefault(e.building, []).append(e)
        extra_rows = incident_rows()[len(INCIDENT_BASE):]
        with transaction.atomic():
            n = seed_incidents(date.today(), djtz.now(), residents,
                               cgs_by_building, extra_rows)
        print(f"✓ 补种异常上报 {n} 条（待处理 {sum(1 for x in extra_rows if not x[4])}）")
        return

    # 外科手术模式：滚动保鲜告警（2026-09-12，每日 cron 用）——异常上报的
    # 日期锚定运行日近两周，几天后"最新告警"就变旧（demo_day_check 红项）。
    # 本模式删全量重播 BASE+EXTRA 锚定今天，效果与全量重灌的异常域完全一致，
    # 但不动其他域，与常驻 runserver 并行安全。注意：会清掉测试期手工上报
    # 的真实行（演示库语义，与全量重灌相同）。
    if "--refresh-incidents" in sys.argv:
        residents = list(Resident.objects.order_by("id"))
        employees = list(Employee.objects.order_by("id"))
        cgs_by_building: dict[str, list[Employee]] = {}
        for e in employees:
            if e.is_caregiver and e.building:
                cgs_by_building.setdefault(e.building, []).append(e)
        rows_all = incident_rows()
        with transaction.atomic():
            deleted, _ = IncidentReport.objects.all().delete()
            n = seed_incidents(date.today(), djtz.now(), residents,
                               cgs_by_building, rows_all)
        print(f"✓ 告警滚动保鲜：删 {deleted} 条 → 重播 {n} 条"
              f"（待处理 {sum(1 for x in rows_all if not x[4])}）锚定 {date.today()}")
        return

    # 外科手术模式：回填档案层入住日期（2026-08-26，入离院记录台账上线后）——
    # 纯 UPDATE 只填 NULL 幂等，不动动态层，与常驻 runserver 并行安全。口径：
    # 建院以来陆续入住（约 3 个月～3 年 3 个月前）；确定性散布按 id 派生不靠
    # 随机，重跑稳定。统一 ≥90 天前：人人早于账期起点(-2 月)、杨国华身故
    # 离院(上月 20 日)与张国栋转区(本月 1 日)等所有已造事件
    if "--seed-admission-dates" in sys.argv:
        anchor = date.today()
        filled = 0
        with transaction.atomic():
            for r in Resident.objects.filter(admission_date__isnull=True).order_by("id"):
                r.admission_date = anchor - timedelta(days=90 + (r.id * 263) % 1095)
                r.save(update_fields=["admission_date"])
                filled += 1
        print(f"✓ 入住日期回填 {filled} 位（库内共 {Resident.objects.count()} 位，已有日期的跳过）")
        return

    # 幂等补未来数周周菜单：周选点餐默认锚「下周一」、家属点下周餐同源，
    # 没有菜单两端都会显示「该周暂无菜单」。已有该周数据则整周跳过，
    # 轮换锚用周序号（toordinal//7），重跑同一周生成一致
    if "--seed-menus-ahead" in sys.argv:
        _i = sys.argv.index("--seed-menus-ahead")
        try:
            weeks_ahead = max(1, int(sys.argv[_i + 1]))
        except (IndexError, ValueError):
            weeks_ahead = 4
        dish_pools = {
            c: list(Dish.objects.filter(category=c, is_available=True)
                    .values_list("id", "name"))
            for c in ("荤菜", "素菜", "主食", "汤", "小菜")
        }
        this_monday = date.today() - timedelta(days=date.today().weekday())
        targets = [this_monday + timedelta(weeks=k) for k in range(weeks_ahead + 1)]
        existing = set(WeekMenu.objects.filter(
            week_start__in=targets).values_list("week_start", flat=True))
        rows = 0
        with transaction.atomic():
            for ws in targets:
                if ws in existing:
                    continue
                wk = ws.toordinal() // 7
                menus, links = [], []
                for di, day_name in enumerate(
                    ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                ):
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
                        links.append((m, picks))
                WeekMenu.objects.bulk_create(menus)
                WeekMenu.dishes.through.objects.bulk_create(
                    [WeekMenu.dishes.through(weekmenu_id=m.pk, dish_id=d)
                     for m, picks in links for d in picks]
                )
                rows += len(menus)
        skipped = len(existing)
        latest = WeekMenu.objects.order_by(
            "-week_start").values_list("week_start", flat=True).first()
        print(f"✓ 周菜单补 {rows} 行（本周起共 {weeks_ahead + 1} 周窗口，"
              f"已有 {skipped} 周跳过，库内最新至 {latest}）")
        return

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
    if "--cover-until" in sys.argv:  # 演示季覆盖：点餐/周菜单/排班前铺到指定日
        _i = sys.argv.index("--cover-until")
        try:
            _until = date.fromisoformat(sys.argv[_i + 1])
        except (IndexError, ValueError):
            sys.exit("✗ --cover-until 需要 YYYY-MM-DD 参数")
        span_end = max(span_end, _until)
    # 演示留白：这些老人锚定日后不预点（周选点餐/家属代点是"从零点起"的演示，
    # 防重约束 (老人,日期,餐次) 下预点满会整批 400）。默认张国栋+李秀兰
    # （录屏脚本两处点餐主角+家属双绑）；--demo-free 1,2,5 换名单，none 关闭。
    demo_free: set[int] = {1, 2}
    if "--demo-free" in sys.argv:
        _i = sys.argv.index("--demo-free")
        try:
            _raw = sys.argv[_i + 1]
        except IndexError:
            sys.exit("✗ --demo-free 需要逗号分隔的老人 id（如 1,2；none 关闭）")
        demo_free = set() if _raw.lower() in ("none", "-", "") else {
            int(x) for x in _raw.split(",") if x.strip()}
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

        # ── 2.2 档案层双语覆盖（P5）：菜品重分类必须先于改名（DISH_RULES
        #        按中文名关键词匹配）；改名后 zh 重灌反向改回，可逆 ──
        overlay_archive()
        # 改名后重取档案：内存里的 residents/employees 还是旧名字（ordered_by /
        # staff_name 等 DenormName 字段要跟着新名字走）
        residents = list(Resident.objects.order_by("id"))
        employees = list(Employee.objects.order_by("id"))

        # ── 2.5 家属账号种子（档案层语义：幂等 get_or_create，不进清空列表）──
        seed_family()

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
                "standing": T("standing_requests").get(r.id, ""),
            }
        orders, order_links, mod_logs, order_times, mod_times = [], [], [], [], []
        for r in residents:
            p = random.Random(f"{SEED}-orders-{r.id}")
            cgs = cgs_by_building.get(r.building, [])
            for d in daterange(span_start, span_end):
                if r.id == DISCHARGE_ID and d >= discharge_date:
                    continue  # 身故离院后不再点餐
                if d > anchor and r.id in demo_free:
                    continue  # 演示留白：锚定日后不预点，现场点餐演示有位
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
                                T("cancel_weekend") if is_weekend else T("cancel_weekday")
                            )
                        elif p.random() < 0.025:
                            swap = pool_pick(dish_pools, "素菜", d.day * 31 + r.id, 1,
                                             avoid=set(chosen[:-1]))
                            if swap:
                                old = dish_names.get(chosen[-1], "?")
                                chosen = chosen[:-1] + swap
                                status, reason = "modified", T("mod_fmt").format(
                                    old=old, new=dish_names.get(swap[0], "?"),
                                    reason=p.choice(T("modify_reasons")))
                    standing = persona[r.id]["standing"]
                    occasional = p.choice(T("occasional")) if p.random() < 0.04 else ""
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
        if demo_free:
            free_names = "、".join(r.name for r in residents if r.id in demo_free) or str(demo_free)
            print(f"  演示留白：{free_names} 锚定日后未预点（周选/家属点餐演示位）")

        # ── 5. 其他域（轻量、相对日期）────────────────────────────
        gen_other_domains(anchor, residents, employees, cgs_by_building,
                          ahead_days=(span_end - anchor).days)

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
                    discharge_date=discharge_date, reason=T("discharge_reason"),
                )
                TransferRecord.objects.create(
                    resident=Resident.objects.get(pk=PROMOTION_ID),
                    from_zone="自理区", to_zone="介护区",
                    transfer_date=anchor.replace(day=1),
                    reason=T("transfer_reason"),
                )
            m_end = month_end(date.fromisoformat(m + "-01"))
            for idx, (rid, cdate, to_l, target, reason, by) in enumerate(timeline):
                if idx in applied or cdate > m_end:
                    continue
                r = Resident.objects.get(pk=rid)
                # 走真实评估定级：26 项打分 → 建议档=目标档 → confirm 原子翻转
                # 档案 + 生成关联变更行（from 取当时档位，链条自然衔接）
                a = create_assessment(r, cdate, tr("李护士"), tr("王护士"), synth_scores(target))
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
                b.settle(operator=tr("孙财务"))
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
                                    tr("李护士"), tr("王护士"), synth_scores(10))
        a_stale.confirm(operator=tr("刘主任"))
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


# ── 异常上报（健康告警）剧本 ──────────────────────────────────────────
# 口径：真实养老院告警呈金字塔（危急少、一般多）；类别与护理等级匹配
# （失智→走失/情绪，全护→摔倒/皮肤/病情，自理→慢病指标/情绪）。时间铺
# 近两周、时段贴事件节律（起夜/餐后/日落后徘徊）。元组：
# (老人id, 类别, 严重度, 说明, 已处理, 距今天数, 时, 分, 处理耗时分钟, 处理人覆盖|None)
INCIDENT_BASE = [
    # 首版 6 条（2026-08-24）——老页面的原始底子
    (7, "refuse_eat", "warning", "午餐拒食，护理人员耐心劝导后进食少量", True, 1, 12, 25, 95, None),
    (4, "fall", "danger", "走廊不慎跌倒，已送医检查，无骨折", True, 1, 10, 10, 130, None),
    (19, "mood", "info", "思念家属情绪低落，已联系家属视频", True, 1, 15, 0, 60, None),
    (26, "skin", "warning", "骶尾部皮肤发红，已开始减压护理", True, 2, 10, 5, 160, None),
    (7, "refuse_eat", "info", "早餐进食少，持续观察", False, 0, 7, 20, 0, None),
    (11, "wander", "warning", "在楼道徘徊寻找出口，已引导回房", False, 0, 9, 40, 0, None),
]
INCIDENT_EXTRA = [
    # 2026-08-25 加密：告警页主从改造后 6 条太稀，补近两周 19 条。
    # 待处理留 1 危急 + 3 紧急 + 2 一般（连同 BASE 未处理共 7 条），让
    # 待处理三档徽章都有内容；1/3 号楼有分布（楼长会话与院长周报口径）。
    # —— 待处理 ——
    (13, "fall", "danger",
     "凌晨起夜在卫生间滑倒，右髋部着地，意识清醒诉局部疼痛，已冰敷制动并联系家属送外院拍片",
     False, 0, 5, 40, 0, None),
    (10, "wander", "warning",
     "晚饭后反复在楼层出口徘徊欲外出，劝返后仍不安定，已加强晚间巡视频率",
     False, 1, 19, 25, 0, None),
    (35, "skin", "warning",
     "骶尾部皮肤破损约2×2cm（II期），已上报护士长更换减压床垫并落实定时翻身",
     False, 1, 10, 5, 0, None),
    (1, "illness", "warning",
     "晨间血压 182/104 mmHg 伴头晕，复测仍高，已按医嘱加药并持续监测",
     False, 0, 8, 15, 0, None),
    (9, "mood", "info",
     "午后情绪烦躁不愿参加集体活动，护理员陪同散步聊天后缓解",
     False, 0, 14, 50, 0, None),
    (22, "refuse_eat", "info",
     "午餐进食约一半，主诉饭菜偏咸，已反馈厨房调整口味",
     False, 1, 12, 40, 0, None),
    # —— 已处理（处理耗时从半小时到次日晨，处理人为本楼护理员或主任）——
    (16, "illness", "danger",
     "晨起胸闷气促、血氧饱和度 88%，即转诊区医院，诊断慢性心衰急性加重，对症治疗后返院观察，现平稳",
     True, 8, 6, 30, 45, "吴主任"),
    (30, "fall", "warning",
     "康复训练收尾时重心不稳踉跄，未倒地，右膝轻微擦伤，已消毒包扎",
     True, 5, 16, 20, 35, None),
    (17, "illness", "warning",
     "晚间诉心悸，心率 102 次/分，静卧休息半小时后复测 88 次/分，继续观察",
     True, 9, 20, 50, 55, None),
    (31, "refuse_eat", "warning",
     "连续两餐进食不足三分之一，体重较上月下降 1.5kg，已预约吞咽功能评估",
     True, 4, 11, 50, 180, None),
    (29, "wander", "warning",
     "下午在5号楼门厅徘徊欲外出，门禁刷脸提醒后引导回房，已电话告知家属",
     True, 6, 15, 10, 40, None),
    (25, "skin", "warning",
     "足跟部压红未破损（Ⅰ期），已佩戴减压足套并落实 q2h 翻身",
     True, 10, 9, 30, 65, None),
    (12, "fall", "warning",
     "浴室门口地面湿滑踉跄未跌倒，扶住扶手，已加铺防滑垫并张贴警示标识",
     True, 14, 8, 50, 30, None),
    (8, "illness", "info",
     "午间测血糖 8.9 mmol/L 偏高，告知控制甜食摄入，晚餐前复测 7.2",
     True, 2, 13, 40, 70, None),
    (27, "mood", "info",
     "因同屋老人出院情绪低落回避交流，社工介入陪伴两次后好转",
     True, 7, 10, 30, 240, None),
    (19, "wander", "info",
     "傍晚定向障碍，坚称要回家，安抚引导后情绪稳定",
     True, 12, 18, 5, 50, None),
    (6, "mood", "info",
     "家属临时取消探视后情绪低落，当晚安排视频通话后平复",
     True, 3, 19, 45, 120, None),
    (21, "skin", "info",
     "左前臂抓痕（自行搔抓），已修剪指甲并外用止痒药膏",
     True, 13, 14, 20, 45, None),
    (36, "refuse_eat", "info",
     "晚餐食欲差进食少，次晨早餐恢复良好",
     True, 11, 18, 30, 660, None),
]


def seed_incidents(anchor, now, residents, cgs_by_building, rows) -> int:
    """异常上报播种 + auto_now_add 时间回填。

    created_at 是 auto_now_add，bulk_create 的 pre_save 会覆盖构造参数，
    须事后 raw UPDATE 回填（与点餐 created_at 同一陷阱）。处理人默认
    本楼护理员（cg_of），剧本可点名覆盖（如转诊类由主任处理）。
    """
    by_id = {r.id: r for r in residents}
    incs, times = [], []
    for rid, cat, sev, desc, handled, off, hh, mm, delay, op in rows:
        r = by_id[rid]
        created = min(aware(anchor - timedelta(days=off), hh, mm), now - timedelta(minutes=5))
        handled_at = min(created + timedelta(minutes=delay), now) if handled else None
        cgs = cgs_by_building.get(r.building, [])
        cg = cgs[r.id % len(cgs)] if cgs else None
        # 未处理行不带处理人——口径干净：没有"处理"就没人署名（旧演示
        # 数据有 pending 行自带处理人的瑕疵，详情页只在 handled 时展示
        # 才没露馅，新数据从源头改掉）
        by = (tr(op) if op else (cg.name if cg else ""))[:30] if handled else ""
        incs.append(IncidentReport(
            resident=r, category=cat, severity=sev, description=desc,
            handled=handled,
            handled_by=by,
            handled_by_emp=cg if (cg and handled and not op) else None,
            handled_at=handled_at,
        ))
        times.append((created, handled_at))
    IncidentReport.objects.bulk_create(incs, batch_size=100)
    with connection.cursor() as cur:
        cur.executemany(
            "UPDATE incidents_incidentreport SET created_at=?, handled_at=? WHERE id=?",
            [(c, h, i.pk) for (c, h), i in zip(times, incs, strict=True)],
        )
    return len(incs)


def gen_other_domains(anchor, residents, employees, cgs_by_building,
                      ahead_days: int = 3) -> None:
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
                detail=p.choice(T("log_details")),
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
                note=T("note_stable") if rp.random() < 0.8 else T("note_high"),
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
                activities=p.choice(T("activities")),
                mood=p.choice(T("moods")),
            ))
    ResidentRoutine.objects.bulk_create(rts, batch_size=500)

    # 用药记录：常见老年慢病用药，1/4 已停用留痕
    meds = T("meds")
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
                note=T("med_stop_note") if stopped else "",
            ))
    MedicationRecord.objects.bulk_create(mrs, batch_size=500)

    # 任务：楼栋主任派给本楼护理员
    leads = [e for e in employees if not e.is_caregiver and e.building]
    tasks = []
    task_seed = T("task_seed")
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

    # 排班+考勤：护理员近 7 天 + 未来若干天（默认 3，--cover-until 可延长）
    scheds, atts = [], []
    for bld, cgs in cgs_by_building.items():
        floors = sorted({r.floor for r in residents if r.building == bld})
        for cg in cgs:
            for off in range(-7, ahead_days + 1):
                d = anchor + timedelta(days=off)
                if (cg.id + d.toordinal()) % 7 == 6:
                    continue  # 休一天
                night = (cg.id + d.isocalendar()[1]) % 2 == 0
                scheds.append(Schedule(
                    employee=cg, date=d, shift="夜班" if night else "白班",
                    building=bld, floor=floors[cg.id % len(floors)] if floors else "",
                    task_note=T("sched_night") if night else T("sched_day"),
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

    # 绩效：主任/组长 近两月（P5：en 模式员工名是 Director/Team Lead，按英文名匹配）
    perf = []
    role_marks = ("Director", "Team Lead") if LANG == "en" else ("主任", "组长")
    reviewers = [e for e in employees if any(mk in e.name for mk in role_marks)][:12]
    for back in (2, 1):
        m = month_str(shift_month(anchor, -back))
        for e in reviewers:
            att_s = 90 + (e.id * 7 + back) % 10
            qty_s = 88 + (e.id * 11 + back) % 12
            perf.append(Performance(
                employee=e, month=m, attendance_score=att_s, quality_score=qty_s,
                total_score=round((att_s + qty_s) / 2),
                comment=T("perf_comment") if qty_s >= 94 else "",
            ))
    Performance.objects.bulk_create(perf, batch_size=100)

    # 出入库：近一周（bulk 绕过 save 钩子 → 不改档案层库存数量，低库存状态保持）
    items = list(InventoryItem.objects.order_by("id"))
    suppliers = T("suppliers")
    sins = [StockIn(item=items[(i + 1) % len(items)], quantity=qty, supplier=suppliers[i % 3],
                    date=anchor + timedelta(days=off), operator=tr(op))
            for i, (off, qty, op) in enumerate([
                (-6, 100, "陈总务"), (-6, 80, "陈总务"), (-5, 500, "赵总务"), (-5, 1000, "赵总务"),
                (-4, 50, "陈总务"), (-3, 300, "陈总务"), (-2, 30, "赵总务"), (-1, 50, "陈总务")])]
    souts = [StockOut(item=items[(i * 2 + 3) % len(items)], quantity=qty, taken_by=tr(taker),
                      date=anchor + timedelta(days=off))
             for i, (off, qty, taker) in enumerate([
                 (-5, 20, "李护士"), (-5, 100, "王护士"), (-4, 200, "王护士"), (-4, 10, "陈总务"),
                 (-3, 50, "张护士"), (-2, 5, "李护士"), (-2, 10, "王护士"), (-1, 30, "张护士")])]
    StockIn.objects.bulk_create(sins, batch_size=100)
    StockOut.objects.bulk_create(souts, batch_size=100)

    # 审批 / 巡检 / 报修 / 异常上报（P5：标题/内容/备注走 _T；申请人/检查人/
    # 报修人走 tr()；巡检结果/区域/楼栋引用等枚举与锚点值不动）
    Approval.objects.bulk_create([
        Approval(applicant_name=tr(n), approval_type=t, title=ti, content=c, status=s)
        for n, t, ti, c, s in T("approvals")
    ], batch_size=100)
    Inspection.objects.bulk_create([
        Inspection(inspector_name=tr(n), area=a, date=anchor + timedelta(days=off),
                   result=res, note=note)
        for n, a, off, res, note in T("inspections")
    ], batch_size=100)
    MaintenanceOrder.objects.bulk_create([
        MaintenanceOrder(
            equipment_name=eq, location=loc, fault_description=f,
            reported_by=tr(by), status=st,
            resolved_at=aware(anchor - timedelta(days=1), 15) if st == "done" else None,
        )
        for eq, loc, f, by, st in T("maintenance")
    ], batch_size=100)
    rows_all = incident_rows()
    incs = seed_incidents(anchor, djtz.now(), residents, cgs_by_building, rows_all)
    print(f"  异常上报：{incs} 条（待处理 {sum(1 for x in rows_all if not x[4])}）")


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

    # 11. 楼栋/楼层缓存与台账一致（P5b：overlay 改名漏列在此暴露——
    #     缓存列还是旧语言值时不在台账 name 集合里，直接 fail）
    bld_names = set(Building.objects.values_list("name", flat=True))
    flr_names = set(Floor.objects.values_list("name", flat=True))
    bad_r_b = (set(Resident.objects.exclude(building="").values_list("building", flat=True))
               - bld_names)
    bad_r_f = (set(Resident.objects.exclude(floor="").values_list("floor", flat=True))
               - flr_names)
    bad_e = (set(Employee.objects.exclude(building="").values_list("building", flat=True))
             - bld_names)
    bad_s_b = set(Schedule.objects.values_list("building", flat=True)) - bld_names
    bad_s_f = set(Schedule.objects.exclude(floor="").values_list("floor", flat=True)) - flr_names
    check(not bad_r_b, f"Resident.building 有值不在台账：{bad_r_b}")
    check(not bad_r_f, f"Resident.floor 有值不在台账：{bad_r_f}")
    check(not bad_e, f"Employee.building 有值不在台账：{bad_e}")
    check(not bad_s_b, f"Schedule.building 有值不在台账：{bad_s_b}")
    check(not bad_s_f, f"Schedule.floor 有值不在台账：{bad_s_f}")
    print("  全部通过 ✓")


if __name__ == "__main__":
    main()
