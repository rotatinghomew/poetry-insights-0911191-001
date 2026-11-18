# 诗词互动导览邀请试验的扩场决策

本项目保存诗词互动导览试验所需的合成班级、签到及小测资料，使用 UTF-8 CSV。空字段表示记录未提供，不应视作数值为零。

## 数据

- `data/allocation.csv`：学校班级分组和场馆时段容量。
- `data/students.csv`：与分组对应的学生名册。
- `data/attendance.csv`：场馆签到、班级和签到来源。
- `data/quiz.csv`：期初和期末小测及缺答记录。

## 环境与验证

需要 Python 3.11 或更新版本；项目仅使用 Python 标准库。可用 `python3 -m unittest discover -s tests -v` 检查 CSV 结构与本地资料完整性。
