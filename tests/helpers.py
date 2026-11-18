"""测试共享辅助：构造小型试验数据目录。"""
from __future__ import annotations

import csv
from pathlib import Path

from tourtrial import io, panel as panel_mod


def write_csv(root: Path, name: str, header: list[str], rows: list[list]):
    with (root / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def base_tables(n_per_class: int = 10):
    """两校四班：甲校 A1(诗词互动)/A2(常规导览)，乙校 B1/B2；每校一个共用场次。"""
    students, allocation, attendance, quiz = [], [], [], []
    specs = [("甲校", "A1", "诗词互动", "周六上午", "西廊", 30, "A1"),
             ("甲校", "A2", "常规导览", "周六上午", "西廊", 30, "A2"),
             ("乙校", "B1", "诗词互动", "周六下午", "南院", 30, "B1"),
             ("乙校", "B2", "常规导览", "周六下午", "南院", 30, "B2")]
    sid_seq = 0
    for school, cls, arm, slot, venue, cap, prefix in specs:
        allocation.append([school, cls, n_per_class, arm, venue, slot, cap])
        for i in range(n_per_class):
            sid_seq += 1
            sid = f"{prefix}{i+1:02d}"
            students.append([sid, school, cls])
            # 处理班 8/10 到馆，对照班 4/10 到馆
            attend = i < (8 if arm == "诗词互动" else 4)
            if attend:
                attendance.append([f"E{sid_seq:03d}", cls, sid, slot, "09:1%d" % (i % 10), "入口终端A"])
            # 期初全测；期末到馆者全测、未到馆者半数缺测
            base = 5 + (i % 3)
            quiz.append([sid, cls, "期初", base, "true"])
            if attend:
                quiz.append([sid, cls, "期末", base + (2 if arm == "诗词互动" else 0), "true"])
            elif i % 2 == 0:
                quiz.append([sid, cls, "期末", "", "false"])
            else:
                quiz.append([sid, cls, "期末", base, "true"])
    return students, allocation, attendance, quiz


def make_dir(root: Path, students=None, allocation=None, attendance=None, quiz=None,
             bookings=None, invitations=None, sessions=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    s, a, at, q = base_tables()
    write_csv(root, "students", ["student_id", "school", "class_id"],
              students if students is not None else s)
    write_csv(root, "allocation",
              ["school", "class_id", "students", "invitation_arm", "venue", "slot", "seat_capacity"],
              allocation if allocation is not None else a)
    write_csv(root, "attendance",
              ["event_id", "class_id", "student_id", "slot", "arrived_at", "source"],
              attendance if attendance is not None else at)
    write_csv(root, "quiz", ["student_id", "class_id", "wave", "score", "answered"],
              quiz if quiz is not None else q)
    if bookings is not None:
        write_csv(root, "bookings",
                  ["booking_id", "student_id", "slot", "requested_at", "status"], bookings)
    if invitations is not None:
        write_csv(root, "invitations",
                  ["student_id", "class_id", "invitation_arm", "sent_at"], invitations)
    if sessions is not None:
        write_csv(root, "sessions", ["slot", "venue", "seat_capacity"], sessions)
    return root


def load(root: Path):
    data = io.load_data(root)
    return data, panel_mod.build_panel(data)


def write_plan(root: Path, rows: list[list]) -> Path:
    path = root / "plan.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["school", "venue", "slot", "seat_capacity",
                         "expected_classes", "expected_students"])
        writer.writerows(rows)
    return path
