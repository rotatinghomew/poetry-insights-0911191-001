"""数据读取与校验。

约定：
- 所有 CSV 使用 UTF-8；空字段表示"未提供"，绝不当作数值零。
- 学校提供：students.csv（期初名册）、allocation.csv（原始分配，含场次与容量）。
- 场馆提供：attendance.csv（签到）、quiz.csv（小测，与是否到馆分开记录），
  以及可选的 sessions.csv（可选场次）、bookings.csv（预约结果）、
  invitations.csv（实际发出/收到的邀请记录）。
- 任何无法识别的记录都进入"未匹配"清单并记入 issues，不得凭场次补分给某个班。
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# 必填文件及其必需列
REQUIRED = {
    "students": ["student_id", "school", "class_id"],
    "allocation": ["school", "class_id", "students", "invitation_arm", "venue", "slot", "seat_capacity"],
    "attendance": ["event_id", "class_id", "student_id", "slot", "arrived_at", "source"],
    "quiz": ["student_id", "class_id", "wave", "score", "answered"],
}

# 选填文件及其必需列
OPTIONAL = {
    "sessions": ["slot", "venue", "seat_capacity"],
    "bookings": ["booking_id", "student_id", "slot", "requested_at", "status"],
    "invitations": ["student_id", "class_id", "invitation_arm", "sent_at"],
}

BOOKING_STATUSES = {"confirmed", "rejected_full", "cancelled"}
BASELINE_WAVE = "期初"
ENDLINE_WAVE = "期末"


@dataclass
class TrialData:
    """一次试验的全部输入。"""

    students: list[dict]
    allocation: list[dict]
    attendance: list[dict]
    quiz: list[dict]
    sessions: list[dict] | None = None
    bookings: list[dict] | None = None
    invitations: list[dict] | None = None
    issues: list[str] = field(default_factory=list)
    inputs_hash: str = ""

    @property
    def arms(self) -> list[str]:
        seen: list[str] = []
        for row in self.allocation:
            arm = row["invitation_arm"]
            if arm and arm not in seen:
                seen.append(arm)
        return seen


def _read_csv(path: Path, required_cols: list[str], issues: list[str]) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} 缺少必需列: {', '.join(missing)}")
        rows = []
        for lineno, row in enumerate(reader, start=2):
            clean = {k: (v.strip() if v is not None else "") for k, v in row.items() if k is not None}
            if all(v == "" for v in clean.values()):
                continue  # 整行空白，跳过
            clean["__line__"] = lineno
            rows.append(clean)
        return rows


def _hash_inputs(files: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(files[name].read_bytes())
    return digest.hexdigest()[:16]


def load_data(data_dir: str | Path) -> TrialData:
    """读取数据目录，返回 TrialData；结构问题抛 ValueError，行级问题记入 issues。"""
    root = Path(data_dir)
    issues: list[str] = []
    found: dict[str, Path] = {}
    tables: dict[str, list[dict]] = {}

    for name, cols in REQUIRED.items():
        path = root / f"{name}.csv"
        if not path.exists():
            raise ValueError(f"缺少必需文件: {path}")
        found[name] = path
        tables[name] = _read_csv(path, cols, issues)

    for name, cols in OPTIONAL.items():
        path = root / f"{name}.csv"
        if path.exists():
            found[name] = path
            tables[name] = _read_csv(path, cols, issues)
        else:
            tables[name] = None  # type: ignore[assignment]

    data = TrialData(
        students=tables["students"],
        allocation=tables["allocation"],
        attendance=tables["attendance"],
        quiz=tables["quiz"],
        sessions=tables["sessions"],
        bookings=tables["bookings"],
        invitations=tables["invitations"],
        issues=issues,
        inputs_hash=_hash_inputs(found),
    )
    _validate(data)
    return data


def _validate(data: TrialData) -> None:
    issues = data.issues

    seen_students: set[str] = set()
    for row in data.students:
        sid = row["student_id"]
        if not sid:
            issues.append(f"students.csv 第{row['__line__']}行: student_id 为空，该行不可用")
            continue
        if sid in seen_students:
            issues.append(f"students.csv 第{row['__line__']}行: student_id {sid} 重复")
        seen_students.add(sid)
        if not row["school"] or not row["class_id"]:
            issues.append(f"students.csv 第{row['__line__']}行: 学校或班级为空 (student_id={sid})")

    seen_classes: set[tuple[str, str]] = set()
    for row in data.allocation:
        key = (row["school"], row["class_id"])
        if key in seen_classes:
            issues.append(f"allocation.csv 第{row['__line__']}行: 班级 {key} 的分配重复出现")
        seen_classes.add(key)
        if not row["invitation_arm"]:
            issues.append(f"allocation.csv 第{row['__line__']}行: 班级 {key} 缺少 invitation_arm")
        try:
            if int(row["seat_capacity"]) <= 0:
                issues.append(f"allocation.csv 第{row['__line__']}行: seat_capacity 非正数")
        except ValueError:
            issues.append(f"allocation.csv 第{row['__line__']}行: seat_capacity 无法解析: {row['seat_capacity']!r}")

    if data.bookings:
        for row in data.bookings:
            if row["status"] and row["status"] not in BOOKING_STATUSES:
                issues.append(
                    f"bookings.csv 第{row['__line__']}行: 未知 status {row['status']!r}"
                    f"（可选值: {sorted(BOOKING_STATUSES)}）"
                )

    for row in data.quiz:
        if row["wave"] not in (BASELINE_WAVE, ENDLINE_WAVE):
            issues.append(f"quiz.csv 第{row['__line__']}行: 未知 wave {row['wave']!r}")
