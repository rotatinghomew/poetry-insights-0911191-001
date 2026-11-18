# 诗词互动导览邀请试验的扩场决策

本项目保存诗词互动导览试验所需的合成班级、签到及小测资料，使用 UTF-8 CSV。空字段表示记录未提供，不应视作数值为零。

试验负责人用 `tourtrial` 工具在安排下一批学校名额之前回答两个问题：试验测到了什么、哪些结论不能推广。方法口径见 [docs/methodology.md](docs/methodology.md)。

## 数据

- `data/allocation.csv`：学校班级分组和场馆时段容量。
- `data/students.csv`：与分组对应的学生名册。
- `data/attendance.csv`：场馆签到、班级和签到来源。
- `data/quiz.csv`：期初和期末小测及缺答记录。

场馆还可补交：`sessions.csv`（可选场次）、`bookings.csv`（预约结果）、`invitations.csv`（实际发放记录），工具会自动采用。

## 工具用法

仅依赖 Python 3.11+ 标准库，入口为 `python3 -m tourtrial`：

```bash
python3 -m tourtrial build-panel --data data --out out/panel.csv   # 学生事实表
python3 -m tourtrial show --data data --student S101               # 单个学生三类事实
python3 -m tourtrial analyze --data data --out out/analysis.md     # ITT 效果与缺测敏感性
python3 -m tourtrial capacity --data data --out out/capacity.md    # 场次容量与席位压力
python3 -m tourtrial review --data data --school 莲池小学 \
    --plan plan.csv --out out/review.md                            # 扩场复核证据包与建议
python3 -m tourtrial sign --data data --school 莲池小学 --plan plan.csv \
    --reviewer 负责人 --note "……" --log decisions.jsonl            # 签发（追加台账）
python3 -m tourtrial history --school 莲池小学 --log decisions.jsonl
```

要点：

- 原始分组不可变；实际收到什么、有没有可用名额、最终有没有参加分别成列可查；
  无法识别的签到绝不凭场次分给某个班。
- 效果按随机分配与学校内比较口径估计；不确定性以班级聚类标准误和校内班级
  置换的随机化推断反映，不把学生视作独立随机。
- 未测的学生不算答错；结论附最好/最坏情形界与临界点 Δ 的缺测敏感性范围。
- 扩场名单不得直接沿用试验场次；拟用场次的接待量或班级重叠超出试验比较
  支持范围时方案退回待复核，不按平均提升自动放大发放量；单纯发错一封邀请
  不会让证据充分的学校停试。
- 签发只增不改：补录小测或更正名额后可重新评估，旧决定原样保留。

## 演示

`bash examples/walkthrough.sh` 用一套含错发、满额、无法识别签到与缺测的
合成数据走完全流程（生成数据 → 分析 → 复核 → 签发 → 补录后重新评估）。

## 环境与验证

需要 Python 3.11 或更新版本；项目仅使用 Python 标准库。可用 `python3 -m unittest discover -s tests -v` 检查 CSV 结构、事实表规则、估计口径、扩场门槛与签发台账。
