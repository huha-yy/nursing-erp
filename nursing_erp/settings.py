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

# DeepSeek LLM (用于 OCR 结果的结构化与纠错)
# API key 在 .env 中，这里只放非敏感的默认 URL 和模型名
# 注意：用非推理模型 deepseek-chat——推理模型(v4-flash)会把 token 耗在思维链上，
# max_tokens 小时 content 会被截断为空，导致 OCR 结构化偶发失败。
os.environ.setdefault("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
os.environ.setdefault("DEEPSEEK_MODEL", "deepseek-chat")

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
            {"title": "AI 院长助手", "icon": "smart_toy", "collapsible": True, "items": [
                {"title": "打开 AI Chat", "icon": "smart_toy", "link": "https://chat.eldcare.cn:8443/chat"},
                {"title": "快速记录", "icon": "edit_note", "link": "/quick-log/"},
                {"title": "周选点餐", "icon": "calendar_month", "link": "/weekly-order/"},
            ]},
            {"title": "老人照护", "icon": "elderly", "collapsible": True, "items": [
                {"title": "老人档案", "icon": "person", "link": "/admin/residents/resident/"},
                {"title": "护理日志", "icon": "edit_note", "link": "/admin/residents/nursinglog/"},
                {"title": "健康记录", "icon": "monitor_heart", "link": "/admin/residents/healthrecord/"},
                {"title": "用药记录", "icon": "medication", "link": "/admin/residents/medicationrecord/"},
                {"title": "作息记录", "icon": "bedtime", "link": "/admin/residents/residentroutine/"},
                # 三级目录：父项必须带 link（UNFOLD sites.py 丢弃无 link 项），指向首个子项；
                # 子项渲染依赖项目覆写的 unfold/helpers/app_list.html（支持 item.items 嵌套）
                {"title": "入离院记录", "icon": "swap_horiz", "link": "/admin/residents/admissionrecord/",
                 "items": [
                     {"title": "入住记录", "icon": "login", "link": "/admin/residents/admissionrecord/"},
                     {"title": "离院记录", "icon": "logout", "link": "/admin/residents/dischargerecord/"},
                     {"title": "转区记录", "icon": "cached", "link": "/admin/residents/transferrecord/"},
                 ]},
                {"title": "入住评估", "icon": "fact_check", "link": "/assessments/"},
                {"title": "评估记录", "icon": "assignment_turned_in", "link": "/admin/assessments/assessment/"},
                {"title": "等级映射表", "icon": "tune", "link": "/admin/assessments/gradelevelmap/"},
            ]},
            {"title": "床位管理", "icon": "bed", "collapsible": True, "items": [
                {"title": "床位看板", "icon": "grid_view", "link": "/beds/"},
                {"title": "楼栋台账", "icon": "apartment", "link": "/admin/beds/building/"},
                {"title": "楼层台账", "icon": "layers", "link": "/admin/beds/floor/"},
                {"title": "房间台账", "icon": "meeting_room", "link": "/admin/beds/room/"},
                {"title": "床位台账", "icon": "bed", "link": "/admin/beds/bed/"},
            ]},
            {"title": "人员管理", "icon": "groups", "collapsible": True, "items": [
                {"title": "员工档案", "icon": "badge", "link": "/admin/staff/employee/"},
                {"title": "排班表", "icon": "calendar_month", "link": "/admin/staff/schedule/"},
                {"title": "考勤记录", "icon": "fingerprint", "link": "/admin/staff/attendance/"},
                {"title": "任务派发", "icon": "assignment", "link": "/admin/staff/task/"},
                {"title": "绩效考核", "icon": "trending_up", "link": "/admin/staff/performance/"},
            ]},
            {"title": "院内事务", "icon": "domain", "collapsible": True, "items": [
                {"title": "库存管理", "icon": "inventory", "link": "/admin/operations/inventoryitem/"},
                {"title": "入库记录", "icon": "add_shopping_cart", "link": "/admin/operations/stockin/"},
                {"title": "领用记录", "icon": "remove_shopping_cart", "link": "/admin/operations/stockout/"},
                {"title": "报修工单", "icon": "build", "link": "/admin/operations/maintenanceorder/"},
                {"title": "卫生巡检", "icon": "cleaning_services", "link": "/admin/operations/inspection/"},
                {"title": "审批流程", "icon": "approval", "link": "/admin/operations/approval/"},
            ]},
            {"title": "异常上报", "icon": "warning", "collapsible": True, "items": [
                {"title": "异常记录", "icon": "warning", "link": "/admin/incidents/incidentreport/"},
            ]},
            {"title": "点餐送餐", "icon": "restaurant", "collapsible": True, "items": [
                {"title": "菜品库", "icon": "menu_book", "link": "/admin/meals/dish/"},
                {"title": "周菜单", "icon": "event_note", "link": "/admin/meals/weekmenu/"},
                {"title": "菜单 OCR", "icon": "photo_camera", "link": "/menu-ocr/"},
                {"title": "点餐 OCR", "icon": "receipt_long", "link": "/meal-order-ocr/"},
                {"title": "点餐订单", "icon": "restaurant", "link": "/admin/meals/mealorder/"},
                {"title": "改退餐记录", "icon": "change_circle", "link": "/admin/meals/mealmodificationlog/"},
                {"title": "餐费月结", "icon": "payments", "link": "/admin/meals/mealfinance/"},
                {"title": "食堂看板", "icon": "soup_kitchen", "link": "/kitchen/"},
                {"title": "财务月结", "icon": "account_balance", "link": "/finance/"},
            ]},
            {"title": "财务账单", "icon": "account_balance_wallet", "collapsible": True, "items": [
                {"title": "应收月账单", "icon": "receipt_long",
                 "link": "/admin/billing/monthlybill/"},
                {"title": "价目表", "icon": "price_change", "link": "/admin/billing/feerule/"},
                {"title": "账单看板", "icon": "account_balance_wallet", "link": "/billing/"},
            ]},
            {"title": "家属服务", "icon": "family_restroom", "collapsible": True, "items": [
                {"title": "家属账号", "icon": "family_restroom",
                 "link": "/admin/family/familymember/"},
                {"title": "绑定台账", "icon": "link", "link": "/admin/family/familybinding/"},
            ]},
            {"title": "审计留痕", "icon": "history", "collapsible": True, "items": [
                {"title": "操作日志", "icon": "history",
                 "link": "/admin/auditlog/operationlog/"},
                {"title": "后台操作日志", "icon": "manage_history",
                 "link": "/admin/admin/logentry/"},
            ]},
            {"title": "系统管理", "icon": "settings", "collapsible": True, "items": [
                {"title": "用户账号", "icon": "manage_accounts", "link": "/admin/auth/user/"},
                {"title": "用户组", "icon": "group", "link": "/admin/auth/group/"},
            ]},
        ],
    },
}
