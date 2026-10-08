# nursing-erp 决策日志

与 ai-nursing-home 的 JOURNAL.md 同一惯例：记录关键决策、修复原因、运维口径，
新会话通过它快速恢复上下文。AI 侧（dl-control/chat 界面/PG 演示数据）的记录
在 ai 仓 JOURNAL.md，两边互不重复。

---

## 2026-09-15 · 中英双语化落地（广交会演示）

**核心策略（拍板前实证过）**：中文串直接当 msgid 包 `gettext_lazy`（`_`），
翻译放 `locale/en/LC_MESSAGES/django.po`（zh→en 单向表）。放弃"英文 msgid"方案
——实测会产生假迁移且砸掉 489 条中文断言；中文 msgid 下 zh 默认回退 msgid 本身，
`makemigrations --check` 零迁移。DB 里的枚举值（男/女、楼栋、护理等级）保持中文
原串不动（演示数据与 AI 查询词表依赖），英文显示走翻译层。

- 基础设施：`settings.py` LocaleMiddleware + `LANGUAGES` + unfold
  `SHOW_LANGUAGES`；`urls.py` 挂 `/i18n/setlang/`；侧栏 68 处标题 `_(...)` 包裹。
- 全量文案：models/apps/admin/api/views + 23 个模板 `{% translate %}`；
  en 目录 ~750 条（含 `男→Male`/`女→Female`、楼栋、护理等级）。
- `residents.gender` 补 choices（`0011_alter_resident_gender` 元数据级迁移已上
  生产）；lifecycle 模板改 `get_gender_display`。
- 演示数据：`rebuild_demo_data.py --lang zh|en`（NAME/DISH/INV/UNIT 双语表 +
  `overlay_archive` 楼栋楼层可逆改名，值表与 AI 侧 `BUILDING_ZH_EN` 同源）。
- 测试：`tests/test_i18n.py` + `test_i18n_pages.py`；conftest autouse 防语言
  泄漏（LocaleMiddleware 按 request 激活，进程内 `translation.activate` 会被
  覆盖——验证必须走 `HTTP_ACCEPT_LANGUAGE` 或 cookie）。pytest 256 绿。

## 2026-09-15 · 生产英文演练验收后回中文

- 备份链：`db.sqlite3.bak-en-20260915-162518`（切英文前）、
  `db.sqlite3.bak-en-live-20260915-1756`（英文态回中文前）。
- **runserver 由 systemd 托管**：`systemctl --user stop/start nursing-erp.service`
  （`nursing-erp.service`，Django runserver 0.0.0.0:8765）——直接 kill 会被拉起，
  以为停了其实没停。
- **rebuild 守卫误报**：`pgrep -f manage.py runserver` 会命中 huha-crm（8766），
  确认 ERP 真停后用 `--force` 过守卫。
- 回中文链路：停服 → `rebuild_demo_data.py --force`（默认 zh，档案层回译
  36/41/94/15/117）→ AI 侧两脚本 `--lang zh` → `echo zh > logs/demo_lang`（ai 仓）
  → 楼长/院长重新登录（会话缓存旧语言楼栋值，X-Building 权限链要求同语言）。

## 2026-09-16 · CTO 仓库分支

- 本地加 `cto` remote（`git@github.com:oriionai/dato_prod.git`），main 推为
  `ysy/nursing-erp`（对齐仓内 `ljl/`、`wqx/` 个人前缀惯例）。
- 日常同步：`git push cto main:refs/heads/ysy/nursing-erp`。

## 2026-10-08 · Q4 数据铺满 + 英文演示态一键切换 + 英文残留收口

### Q4 演示数据铺满（zh/en 两语言都做了）
- `restore_demo.sh` 默认 cover-until 改 **2026-12-31**。当前覆盖：
  weekmenu 07-27~12-28（23 周）、mealorder 08-01~12-31、schedule 10-01~12-31；
  PG 侧 meals +273 行（10-05~2027-01-03）、schedules +1482 行。
- 保持"锚定运行日"口径：工单/告警/事故仍由 keepfresh cron 06:23 每日滚，
  **不前铺**（完成率语义）；张国栋(1)/李秀兰(2) demo-free 逻辑不变。
- 备份：`db.sqlite3.bak-20261008-pre-q4cover`、`/tmp/nursing-demo-tables-bak-20261008.sql`。

### 英文演示态一键切换（方案 B + UI 语言跟 marker）
- **`scripts/switch_demo_lang.sh en|zh [--until]`**：备份 sqlite → 停服 →
  ERP `rebuild --lang X --cover-until $COVER --demo-free 1,2 --force` →
  AI 侧 seed_work_orders + seed_pg_demo_en --lang X →
  `sync_pg_meals_from_erp.py`（ERP WeekMenu → PG nursing_meals，staging 表方案，
  幂等保留旧历史）→ 写 `ai-nursing-home/logs/demo_lang` marker → 起服验证。
- **`nursing_erp/demo_lang.py`**（DemoLangDefaultMiddleware，挂在 LocaleMiddleware
  后）：无语言 cookie 的浏览器按 marker 默认英文——一次切换，UI+数据双英文，
  无需每人手动点切换。坑：Django 5.2 **没有** `settings.LANGUAGE_COOKIE` 属性
  （getattr 兜底 `django_language`），首版直接 AttributeError 全站 500、
  KPI 归零——**重启后必须健康检查**。
- compose 挂载 `../logs/:/app/logs:ro` 让 dato-control 读到 marker。

### 英文态中文残留收口（全页面 curl+CJK 扫描排查）
- `rebuild_demo_data.py`：**rebuild 时 activate 目标语言**——模型层 gettext
  构造的持久化文本（评估定级 summary）随语言种入；`DIAGNOSIS_ZH_EN` 37 词
  诊断可逆 overlay（同义词对给不同英文保反查单射）。
- `assessments/models.py` confirm() summary 走 gettext；`views.py` lifecycle
  枚举插值 `_n()` 包裹。
- 模板：weekly_order/quick_log/meal_order_ocr 加 MEAL/CARE_LABELS JS 映射
  （枚举值翻译）+ Building/Floor 拼接加空格；family_order/kitchen_today/
  assessments_board/assessment_detail/assessment_form/resident_lifecycle
  `{% translate %}` 包变量值。
- en django.po 追加：定级 summary 格式串、0-4 级等级标签等，msgfmt 编译。
  （根目录曾出现误编译的 messages.mo 废文件，已删。）
- 排查结论：ERP 13 页+家属端 3 页+Unfold admin 全干净；语言切换器上的
  "中文"标签是惯例保留（显示目标语言名）。

**当前生产 = 英文演示态**。切回：`bash scripts/switch_demo_lang.sh zh`
（AI 仓），切后楼长/院长需重新登录。

### 追记（同日）：admin 筛选器数据值翻译（action / groups 两处漏网）
- **现象**：en 下 /admin/auditlog/operationlog/ 的 "By Action" 与
  /admin/auth/user/ 的 "By groups" 下拉仍中文。
- **根因**：两组都是 **DB 数据值**非模板文案——OperationLog.action 是自由
  文本（record() 埋点 12 个词 + 中间件路径表 11 个词，写入恒中文），
  Group.name 是种子数据行。模板侧无法插手，须在 ListFilter.choices()
  显示层 gettext（与「枚举值不动」同口径）。
- **修复**：`nursing_erp/admin_filters.py` 两个筛选器子类（只翻
  `isinstance(display, str)`——Django 自产 "All" 是 lazy proxy，再翻会把
  zh「全部」卡死）；auditlog admin 换 action 筛选器 + 列表列 action_badge
  翻译；urls.py 运行时替换 UserAdmin.list_filter 的 groups 项；
  OperationLog.__str__ 的 action 也走 gettext（admin 勾选框 title 用它）。
  en po 收录 27 词条（动作 closed vocab + 6 组名）。
- **测试**：test_i18n_pages 新增 admin 筛选用例（en 英/zh 中双向）。
- **顺手修的真回归**：conftest 加 `_isolate_demo_lang_marker`（autouse）——
  demo_lang 中间件读到生产 marker=en 会把无 cookie 的测试请求全部强制
  英文，marker=en 期间 test_i18n_pages zh 用例 7 连挂（本次首跑才发现）。
  pytest 25 绿 + makemigrations --check 零迁移。
