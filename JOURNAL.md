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
