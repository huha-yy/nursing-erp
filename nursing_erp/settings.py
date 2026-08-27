"""
Django settings for nursing_erp project — 养老院业务管理系统
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 加载项目根目录 .env（KEY=VALUE 格式，gitignore，不提交）
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _val = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _val.strip())

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# /api/ 认证密钥（nursing_erp/api_auth.py）：机器调用方带 X-API-Key 头。
# 与 ai-nursing-home/infra/.env 的 NURSING_ERP_API_KEY 同值。未配置则 fail-closed。
ERP_API_KEY = os.environ.get("ERP_API_KEY", "")
# 轻量页 @login_required 未登录时跳转 admin 登录页，登录后回跳原地址
LOGIN_URL = "/admin/login/"
# 登录成功落后台首页——Django 默认 /accounts/profile/ 无此路由，登录后闪 404
LOGIN_REDIRECT_URL = "/admin/"

INSTALLED_APPS = [
    "unfold",                           # Must be before django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "import_export",
    # Project apps (added progressively)
    "residents.apps.ResidentsConfig",
    "staff.apps.StaffConfig",
    "operations.apps.OperationsConfig",
    "incidents.apps.IncidentsConfig",
    "meals.apps.MealsConfig",
    "beds.apps.BedsConfig",
    "billing.apps.BillingConfig",
    "assessments.apps.AssessmentsConfig",
    "family.apps.FamilyConfig",
    "auditlog.apps.AuditlogConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # 审计兜底：/api/* 写请求自动留痕（放最后＝响应链最先执行，
    # 此时 ninja 已把凭据挂在 request.auth 上，能区分 员工/家属/AI）
    "auditlog.middleware.AuditMiddleware",
]

ROOT_URLCONF = "nursing_erp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nursing_erp.wsgi.application"

# Use SQLite for local dev, PostgreSQL for Docker deployment
_db_password = os.environ.get("DB_PASSWORD", "")
if _db_password:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "nursing_erp"),
            "USER": os.environ.get("DB_USER", "nursing"),
            "PASSWORD": _db_password,
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # NURSING_DB 可指到临时库文件——scripts/rebuild_demo_data.py 的
            # 演练/验证通道，不碰生产 db.sqlite3
            "NAME": os.environ.get("NURSING_DB") or BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# External OCR service (Baidu Unlimited-OCR via dl-ocr)
# 敏感 token 在 .env 中，这里只放非敏感的默认 URL
os.environ.setdefault("DL_OCR_URL", "http://192.168.10.247:18080")

# LLM (用于 OCR 结果的结构化与纠错) — 与 ai-nursing-home 同源 Moonshot kimi-k2.6
# API key (LLM_API_KEY) 在 .env 中，这里只放非敏感默认值。
# 2026-08-27 从 DeepSeek 切换（原 key 402 欠费）；llm.py 里 kimi 不传 temperature
# （推理模型只接受默认 1），max_tokens 需预算思维链（调用方传 4000）。
os.environ.setdefault("LLM_BASE_URL", "https://api.moonshot.cn/v1/chat/completions")
os.environ.setdefault("LLM_MODEL", "kimi-k2.6")

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---- 日志 ----
# OCR 识别过程（原始文字 / LLM 结构化结果 / 未匹配菜名）落盘，方便排查。
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "menu_ocr": {
            "format": "[{asctime}] {levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "menu_ocr_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "menu-ocr.log"),
            "maxBytes": 5 * 1024 * 1024,  # 5MB，单文件上限
            "backupCount": 3,             # 保留 3 个轮转备份
            "encoding": "utf-8",
            "formatter": "menu_ocr",
        },
    },
    "loggers": {
        "menu_ocr": {
            "handlers": ["menu_ocr_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# django-unfold settings
from nursing_erp import nav_perms  # noqa: E402  # 须在 UNFOLD 前 import；模块零依赖无环

UNFOLD = {
    "SITE_TITLE": "养老院管理系统",
    "SITE_HEADER": "养老院综合管理平台",
    "SITE_URL": "/",
    "SITE_SYMBOL": "home",
    "COLORS": {
        "primary": {
            "50": "239 246 255",
            "100": "219 234 254",
            "200": "191 219 254",
            "300": "147 197 253",
            "400": "96 165 250",
            "500": "59 130 246",
            "600": "37 99 235",
            "700": "29 78 216",
            "800": "30 64 175",
            "900": "30 58 138",
            "950": "23 37 84",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            # ── 侧栏目录规范（2026-08-26 整理，详见 tests/test_lifecycle_nav.py 规范钉）──
            # 层级：平铺优先，一组超 ~7 条才收拢三级父项（父项 2~4 子，必带 link——
            #   UNFOLD sites.py 丢弃无 link 项；渲染依赖覆写的 app_list.html）
            # 命名后缀：档案=人/物主数据 台账/库/表=配置清单 记录=事件流水
            #   单/账单=业务单据 看板=可视化页
            {"title": "AI 院长助手", "icon": "smart_toy", "collapsible": True, "items": [
                # chat 外链不配 permission：外链全员可见，防组空壳
                {"title": "打开 AI Chat", "icon": "smart_toy", "link": "https://chat.eldcare.cn:8443/chat"},
                {"title": "快速记录", "icon": "edit_note", "link": "/quick-log/",
                 "permission": nav_perms.quick_log},
            ]},
            {"title": "老人照护", "icon": "elderly", "collapsible": True, "items": [
                {"title": "老人档案", "icon": "person", "link": "/admin/residents/resident/",
                 "permission": nav_perms.resident},
                {"title": "照护记录", "icon": "volunteer_activism",
                 "link": "/admin/residents/nursinglog/", "permission": nav_perms.care_records,
                 "items": [
                     {"title": "护理记录", "icon": "edit_note",
                      "link": "/admin/residents/nursinglog/", "permission": nav_perms.nursinglog},
                     {"title": "健康记录", "icon": "monitor_heart",
                      "link": "/admin/residents/healthrecord/",
                      "permission": nav_perms.healthrecord},
                     {"title": "用药记录", "icon": "medication",
                      "link": "/admin/residents/medicationrecord/",
                      "permission": nav_perms.medicationrecord},
                     {"title": "作息记录", "icon": "bedtime",
                      "link": "/admin/residents/residentroutine/",
                      "permission": nav_perms.residentroutine},
                 ]},
                {"title": "入离院记录", "icon": "swap_horiz",
                 "link": "/admin/residents/admissionrecord/",
                 "permission": nav_perms.lifecycle_records,
                 "items": [
                     {"title": "入住记录", "icon": "login",
                      "link": "/admin/residents/admissionrecord/",
                      "permission": nav_perms.admissionrecord},
                     {"title": "离院记录", "icon": "logout",
                      "link": "/admin/residents/dischargerecord/",
                      "permission": nav_perms.dischargerecord},
                     {"title": "转区记录", "icon": "cached",
                      "link": "/admin/residents/transferrecord/",
                      "permission": nav_perms.transferrecord},
                 ]},
                {"title": "评估管理", "icon": "checklist", "link": "/assessments/",
                 "permission": nav_perms.assessment_center,
                 "items": [
                     {"title": "入住评估", "icon": "fact_check", "link": "/assessments/",
                      "permission": nav_perms.assessment},
                     {"title": "评估记录", "icon": "assignment_turned_in",
                      "link": "/admin/assessments/assessment/", "permission": nav_perms.assessment},
                     {"title": "等级映射表", "icon": "tune",
                      "link": "/admin/assessments/gradelevelmap/",
                      "permission": nav_perms.gradelevelmap},
                 ]},
                # 原「异常上报」独立组并入：IncidentReport 挂 resident 外键，属照护域
                {"title": "异常记录", "icon": "warning",
                 "link": "/admin/incidents/incidentreport/",
                 "permission": nav_perms.incidentreport},
            ]},
            {"title": "床位管理", "icon": "bed", "collapsible": True, "items": [
                {"title": "床位看板", "icon": "grid_view", "link": "/beds/",
                 "permission": nav_perms.bed_board},
                {"title": "楼栋台账", "icon": "apartment", "link": "/admin/beds/building/",
                 "permission": nav_perms.building},
                {"title": "楼层台账", "icon": "layers", "link": "/admin/beds/floor/",
                 "permission": nav_perms.floor},
                {"title": "房间台账", "icon": "meeting_room", "link": "/admin/beds/room/",
                 "permission": nav_perms.room},
                {"title": "床位台账", "icon": "bed", "link": "/admin/beds/bed/",
                 "permission": nav_perms.bed},
            ]},
            {"title": "膳食点餐", "icon": "restaurant", "collapsible": True, "items": [
                {"title": "食堂看板", "icon": "soup_kitchen", "link": "/kitchen/",
                 "permission": nav_perms.kitchen_board},
                {"title": "菜品库", "icon": "menu_book", "link": "/admin/meals/dish/",
                 "permission": nav_perms.dish},
                {"title": "周菜单", "icon": "event_note", "link": "/admin/meals/weekmenu/",
                 "permission": nav_perms.weekmenu},
                {"title": "点餐工具", "icon": "touch_app",
                 "link": "/weekly-order/", "permission": nav_perms.order_tools,
                 "items": [
                     {"title": "周选点餐", "icon": "calendar_month",
                      "link": "/weekly-order/", "permission": nav_perms.weekly_order},
                     {"title": "菜单 OCR", "icon": "photo_camera",
                      "link": "/menu-ocr/", "permission": nav_perms.menu_ocr},
                     {"title": "点餐 OCR", "icon": "receipt_long",
                      "link": "/meal-order-ocr/", "permission": nav_perms.meal_order_ocr},
                 ]},
                {"title": "订单台账", "icon": "receipt_long",
                 "link": "/admin/meals/mealorder/", "permission": nav_perms.order_ledger,
                 "items": [
                     {"title": "点餐订单", "icon": "restaurant",
                      "link": "/admin/meals/mealorder/", "permission": nav_perms.mealorder},
                     {"title": "改退餐记录", "icon": "change_circle",
                      "link": "/admin/meals/mealmodificationlog/",
                      "permission": nav_perms.mealmodificationlog},
                 ]},
                # 餐费对账 = 原「财务月结」(/finance/，MealFinance 对账看板)，与餐费月结同数据
                {"title": "餐费结算", "icon": "calculate", "link": "/admin/meals/mealfinance/",
                 "permission": nav_perms.mealfinance,
                 "items": [
                     {"title": "餐费月结", "icon": "payments", "link": "/admin/meals/mealfinance/",
                      "permission": nav_perms.mealfinance},
                     {"title": "餐费对账", "icon": "price_check", "link": "/finance/",
                      "permission": nav_perms.mealfinance},
                 ]},
            ]},
            {"title": "财务账单", "icon": "account_balance_wallet", "collapsible": True, "items": [
                {"title": "应收月账单", "icon": "receipt_long",
                 "link": "/admin/billing/monthlybill/", "permission": nav_perms.monthlybill},
                {"title": "价目表", "icon": "price_change", "link": "/admin/billing/feerule/",
                 "permission": nav_perms.feerule},
                {"title": "账单看板", "icon": "account_balance_wallet", "link": "/billing/",
                 "permission": nav_perms.billing_board},
            ]},
            {"title": "人员管理", "icon": "groups", "collapsible": True, "items": [
                {"title": "员工档案", "icon": "badge", "link": "/admin/staff/employee/",
                 "permission": nav_perms.employee},
                {"title": "排班表", "icon": "calendar_month", "link": "/admin/staff/schedule/",
                 "permission": nav_perms.schedule},
                {"title": "考勤记录", "icon": "fingerprint", "link": "/admin/staff/attendance/",
                 "permission": nav_perms.attendance},
                {"title": "任务派发", "icon": "assignment", "link": "/admin/staff/task/",
                 "permission": nav_perms.task},
                {"title": "绩效考核", "icon": "trending_up", "link": "/admin/staff/performance/",
                 "permission": nav_perms.performance},
            ]},
            {"title": "院内事务", "icon": "domain", "collapsible": True, "items": [
                {"title": "物资管理", "icon": "warehouse",
                 "link": "/admin/operations/inventoryitem/",
                 "permission": nav_perms.material_center,
                 "items": [
                     {"title": "库存台账", "icon": "inventory",
                      "link": "/admin/operations/inventoryitem/",
                      "permission": nav_perms.inventoryitem},
                     {"title": "入库记录", "icon": "add_shopping_cart",
                      "link": "/admin/operations/stockin/", "permission": nav_perms.stockin},
                     {"title": "领用记录", "icon": "remove_shopping_cart",
                      "link": "/admin/operations/stockout/", "permission": nav_perms.stockout},
                 ]},
                {"title": "报修工单", "icon": "build",
                 "link": "/admin/operations/maintenanceorder/",
                 "permission": nav_perms.maintenanceorder},
                {"title": "卫生巡检", "icon": "cleaning_services",
                 "link": "/admin/operations/inspection/", "permission": nav_perms.inspection},
                {"title": "审批流程", "icon": "approval",
                 "link": "/admin/operations/approval/", "permission": nav_perms.approval},
            ]},
            {"title": "家属服务", "icon": "family_restroom", "collapsible": True, "items": [
                {"title": "家属账号", "icon": "family_restroom",
                 "link": "/admin/family/familymember/", "permission": nav_perms.familymember},
                {"title": "绑定台账", "icon": "link", "link": "/admin/family/familybinding/",
                 "permission": nav_perms.familybinding},
            ]},
            {"title": "审计留痕", "icon": "history", "collapsible": True, "items": [
                {"title": "业务操作日志", "icon": "history",
                 "link": "/admin/auditlog/operationlog/", "permission": nav_perms.operationlog},
                {"title": "后台变更日志", "icon": "manage_history",
                 "link": "/admin/admin/logentry/", "permission": nav_perms.logentry},
            ]},
            {"title": "系统管理", "icon": "settings", "collapsible": True, "items": [
                {"title": "用户账号", "icon": "manage_accounts", "link": "/admin/auth/user/",
                 "permission": nav_perms.user_admin},
                {"title": "用户组", "icon": "group", "link": "/admin/auth/group/",
                 "permission": nav_perms.group_admin},
            ]},
        ],
    },
}
