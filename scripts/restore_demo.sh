#!/usr/bin/env bash
# 演示数据一键恢复 — 测试弄脏库后跑这个，回到准备好的演示状态。
#
# 做什么（2026-09-03 定稿的口径）：
#   1. 备份当前库（db.sqlite3.bak-时间戳，做坏了可回滚）
#   2. 停 nursing-erp 服务（重灌拒绝与 runserver 并行）
#   3. 全量重灌：锚定【运行当天】，点餐/周菜单/排班前铺到覆盖日，
#      张国栋(1)+李秀兰(2) 锚定日后留白（点餐演示位）；档案层不动，
#      测试期点的餐/退的单/审批等动态层全部重造
#   4. 补未来 4 周菜单（独立子命令，必须在全量之后跑）
#   5. 起服务
#   6. 验证：服务活着 + 今日有餐 + 演示位干净
#
# 用法：
#   ./scripts/restore_demo.sh                 # 覆盖到 2026-09-30
#   ./scripts/restore_demo.sh 2026-10-31      # 换覆盖截止日（演示季延长时）
#
# 注意：只重置 ERP 业务动态层；档案层（老人/员工/床位/账号/绑定）刻意不动，
# 测试时别在档案层做破坏性操作（删老人、删账号）。PG 侧测试不会弄脏
#（chat 只读），演示当天早上另跑 ai-nursing-home/scripts/seed_work_orders_demo.py。
set -euo pipefail
cd "$(dirname "$0")/.."

COVER=${1:-2026-09-30}
STAMP=$(date +%Y%m%d-%H%M%S)

echo "== 1/6 备份当前库 -> db.sqlite3.bak-$STAMP"
cp db.sqlite3 "db.sqlite3.bak-$STAMP"

echo "== 2/6 停服务"
systemctl --user stop nursing-erp

echo "== 3/6 全量重灌（锚定今天 $(date +%F)，覆盖到 $COVER，张国栋/李秀兰留白）"
uv run python scripts/rebuild_demo_data.py --cover-until "$COVER"

echo "== 4/6 补未来 4 周菜单"
uv run python scripts/rebuild_demo_data.py --seed-menus-ahead 4

echo "== 5/6 起服务"
systemctl --user start nursing-erp
sleep 2

echo "== 6/6 验证"
systemctl --user is-active --quiet nursing-erp && echo "  服务: active"
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/family/login/)
echo "  HTTP: $CODE（200/302 均为正常）"
sqlite3 "file:db.sqlite3?mode=ro" "
SELECT '  今日订单: '||COUNT(*)||' 张（食堂看板数据源）' FROM meals_mealorder
 WHERE date=date('now','localtime');
SELECT '  演示位（张国栋+李秀兰未来有效订单）: '||COUNT(*)||' 张，应为 0'
 FROM meals_mealorder
 WHERE resident_id IN (1,2) AND date>date('now','localtime') AND status!='cancelled';"

echo "== 完成。备份在 db.sqlite3.bak-$STAMP，出问题回滚："
echo "   systemctl --user stop nursing-erp && cp db.sqlite3.bak-$STAMP db.sqlite3 && systemctl --user start nursing-erp"
