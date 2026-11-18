#!/usr/bin/env bash
# 端到端演示：从数据到扩场决定，再到补录后重新评估。
set -euo pipefail
cd "$(dirname "$0")/.."

DEMO=examples/demo_data
OUT=examples/out
LOG=$OUT/decisions.jsonl
rm -rf "$DEMO" "$OUT"

echo "===== 1. 生成演示数据（含错发、满额、无法识别签到、缺测） ====="
python3 examples/make_demo_data.py --out "$DEMO"

echo; echo "===== 2. 学生事实表：原始分组 / 实际收到 / 名额 / 参加 分别可查 ====="
python3 -m tourtrial build-panel --data "$DEMO" --out "$OUT/panel.csv"
python3 -m tourtrial show --data "$DEMO" --student 栖301

echo; echo "===== 3. 效果分析（ITT + 班级聚类 + 随机化推断 + 缺测敏感性） ====="
python3 -m tourtrial analyze --data "$DEMO" --out "$OUT/analysis.md"

echo; echo "===== 4. 场次容量与席位压力 ====="
python3 -m tourtrial capacity --data "$DEMO" --out "$OUT/capacity.md"

echo; echo "===== 5. 望江小学：证据充分、方案合规 -> 批准扩场 ====="
python3 -m tourtrial review --data "$DEMO" --school 望江小学 \
  --plan examples/plan_wangjiang.csv --out "$OUT/review_wangjiang.md"
python3 -m tourtrial sign --data "$DEMO" --school 望江小学 \
  --plan examples/plan_wangjiang.csv --reviewer 试验负责人 \
  --note "分配证据与覆盖充分，拟用场次在试验供给条件内" --log "$LOG"

echo; echo "===== 6. 松风小学：整班错发 -> 证据不足（单封错发则不会停试，见栖霞警告） ====="
python3 -m tourtrial review --data "$DEMO" --school 松风小学 || true

echo; echo "===== 7. 栖霞小学：方案沿用试验场次且更挤 -> 退回待复核 ====="
python3 -m tourtrial review --data "$DEMO" --school 栖霞小学 \
  --plan examples/plan_qixia_bad.csv || true
python3 -m tourtrial sign --data "$DEMO" --school 栖霞小学 \
  --plan examples/plan_qixia_bad.csv --reviewer 试验负责人 \
  --note "拟用场次超出试验支持的供给条件，退回" --log "$LOG"

echo; echo "===== 8. 补录期末小测、改用新场次后重新评估（旧决定保留） ====="
python3 examples/make_demo_data.py --out "$DEMO" --backfill
python3 -m tourtrial sign --data "$DEMO" --school 栖霞小学 \
  --plan examples/plan_qixia_fixed.csv --reviewer 试验负责人 \
  --note "补录小测并改用新场次，复核通过" --log "$LOG"

echo; echo "===== 9. 栖霞小学的签发历史：两次决定都在，后一条取代前一条 ====="
python3 -m tourtrial history --school 栖霞小学 --log "$LOG"
