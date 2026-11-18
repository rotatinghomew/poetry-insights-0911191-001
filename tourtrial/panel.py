"""学生层面事实表。

原则：
1. 原始分组（arm）只来自 allocation.csv，发错邀请、跨班跟随、满额都不改变分组。
2. "实际收到什么""有没有可用名额""最终有没有参加"是三列互相独立的事实，
   各自可空（空 = 未观测，不是"没有"）。
3. 无法识别的签到进入 unmatched_attendance，绝不凭场次分给某个班。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .io import BASELINE_WAVE, ENDLINE_WAVE, TrialData

# 事实表列（build-panel 输出顺序）
PANEL_COLUMNS = [
    "student_id", "school", "class_id", "arm", "venue", "slot",
    "invite_received", "invite_misrouted",
    "booking_attempted", "booking_status", "slot_available",
    "attended", "attended_slot", "attendance_class_recorded", "cross_class_follow",
    "quiz_baseline", "quiz_endline", "quiz_endline_answered",
]


@dataclass
class Panel:
    students: list[dict]
    sessions: dict[str, dict]          # slot -> {venue, capacity, classes, schools}
    unmatched_attendance: list[dict] = field(default_factory=list)
    unmatched_quiz: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def by_school(self, school: str) -> list[dict]:
        return [s for s in self.students if s["school"] == school]

    def get(self, student_id: str) -> dict | None:
        for s in self.students:
            if s["student_id"] == student_id:
                return s
        return None


def _parse_score(raw: str, issues: list[str], where: str) -> float | None:
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        issues.append(f"{where}: score 无法解析 {raw!r}，按缺测处理")
        return None


def build_panel(data: TrialData) -> Panel:
    issues = list(data.issues)

    # ---- 名册 ----
    roster: dict[str, dict] = {}
    for row in data.students:
        sid = row["student_id"]
        if sid and sid not in roster:
            roster[sid] = {"school": row["school"], "class_id": row["class_id"]}

    # ---- 原始分配：班级 -> 组别/场次；场次 -> 容量 ----
    class_alloc: dict[tuple[str, str], dict] = {}
    sessions: dict[str, dict] = {}
    for row in data.allocation:
        key = (row["school"], row["class_id"])
        class_alloc[key] = {
            "arm": row["invitation_arm"], "venue": row["venue"], "slot": row["slot"],
        }
        slot = row["slot"]
        try:
            cap = int(row["seat_capacity"])
        except ValueError:
            cap = None
        sess = sessions.setdefault(slot, {"slot": slot, "venue": row["venue"],
                                          "capacities": [], "classes": [], "schools": set()})
        if sess["venue"] != row["venue"]:
            issues.append(f"场次 {slot} 对应多个场馆（{sess['venue']} / {row['venue']}），请核对")
        if cap is not None:
            sess["capacities"].append(cap)
        if key not in sess["classes"]:
            sess["classes"].append(key)
        sess["schools"].add(row["school"])

    # 可选的场馆场次表可覆盖容量
    if data.sessions:
        for row in data.sessions:
            slot = row["slot"]
            sess = sessions.setdefault(slot, {"slot": slot, "venue": row["venue"],
                                              "capacities": [], "classes": [], "schools": set()})
            try:
                sess["capacity_override"] = int(row["seat_capacity"])
            except ValueError:
                issues.append(f"sessions.csv 第{row['__line__']}行: seat_capacity 无法解析")

    for slot, sess in sessions.items():
        caps = sess.pop("capacities")
        declared = set(caps)
        if len(declared) > 1:
            issues.append(f"场次 {slot} 的容量记录不一致 {sorted(declared)}，保守取最小值")
        sess["capacity"] = sess.pop("capacity_override", None) or (min(declared) if declared else None)
        sess["schools"] = sorted(sess["schools"])

    # ---- 实际收到的邀请（可选记录）----
    invite_by_student: dict[str, str] = {}
    if data.invitations:
        for row in data.invitations:
            arm = row["invitation_arm"]
            sid = row["student_id"]
            if sid:
                if sid in roster:
                    invite_by_student[sid] = arm
                else:
                    issues.append(f"invitations.csv 第{row['__line__']}行: student_id {sid} 不在名册")
            elif row["class_id"]:
                # 班级级发放记录：落到该班名册内每名学生
                for stu_sid, stu in roster.items():
                    if stu["class_id"] == row["class_id"]:
                        invite_by_student.setdefault(stu_sid, arm)
            else:
                issues.append(f"invitations.csv 第{row['__line__']}行: 既无 student_id 也无 class_id")

    # ---- 预约结果（可选记录）：名额是否可用是独立事实 ----
    booking_by_student: dict[str, list[dict]] = {}
    if data.bookings:
        for row in data.bookings:
            sid = row["student_id"]
            if sid in roster:
                booking_by_student.setdefault(sid, []).append(row)
            elif sid:
                issues.append(f"bookings.csv 第{row['__line__']}行: student_id {sid} 不在名册")
        issues.extend(_check_fcfs(data.bookings, sessions, roster))

    # ---- 签到：只按 student_id 认领，无法识别的绝不凭场次分班 ----
    attended: dict[str, list[dict]] = {}
    unmatched_attendance: list[dict] = []
    for row in data.attendance:
        sid = row["student_id"]
        if sid and sid in roster:
            attended.setdefault(sid, []).append(row)
        else:
            unmatched_attendance.append({
                "event_id": row["event_id"], "slot": row["slot"],
                "class_id_recorded": row["class_id"], "source": row["source"],
                "reason": "student_id 为空" if not sid else f"student_id {sid} 不在名册",
            })

    # ---- 小测：与是否到馆分开记录；未测不算答错 ----
    quiz_scores: dict[str, dict[str, float | None]] = {}
    quiz_answered: dict[str, bool] = {}
    unmatched_quiz: list[dict] = []
    for row in data.quiz:
        sid = row["student_id"]
        if sid not in roster:
            unmatched_quiz.append({"student_id": sid, "wave": row["wave"],
                                   "reason": "student_id 不在名册"})
            continue
        if sid in roster and row["class_id"] and row["class_id"] != roster[sid]["class_id"]:
            issues.append(
                f"quiz.csv 第{row['__line__']}行: {sid} 记录班级 {row['class_id']} "
                f"与名册 {roster[sid]['class_id']} 不符，仍按名册班级归属"
            )
        answered = row["answered"].lower() == "true"
        score = _parse_score(row["score"], issues, f"quiz.csv 第{row['__line__']}行")
        if answered and score is None:
            issues.append(f"quiz.csv 第{row['__line__']}行: answered=true 但分数为空，按缺测处理")
            answered = False
        entry = quiz_scores.setdefault(sid, {BASELINE_WAVE: None, ENDLINE_WAVE: None})
        if row["wave"] in entry:
            if entry[row["wave"]] is not None:
                issues.append(f"quiz.csv 第{row['__line__']}行: {sid} {row['wave']} 成绩重复，保留首条")
                continue
            entry[row["wave"]] = score if answered else None
            if row["wave"] == ENDLINE_WAVE:
                quiz_answered[sid] = answered

    # ---- 组装学生事实行 ----
    students: list[dict] = []
    for sid, stu in sorted(roster.items()):
        alloc = class_alloc.get((stu["school"], stu["class_id"]), {})
        arm = alloc.get("arm", "")
        class_slot = alloc.get("slot", "")

        received = invite_by_student.get(sid) if data.invitations else None
        misrouted = (received is not None and arm and received != arm) if data.invitations else None

        books = booking_by_student.get(sid, [])
        if data.bookings:
            attempted = any(b["status"] != "cancelled" for b in books)
            if any(b["status"] == "confirmed" for b in books):
                b_status, available = "confirmed", True
            elif any(b["status"] == "rejected_full" for b in books):
                b_status, available = "rejected_full", False
            elif books:
                b_status, available = "cancelled", None
            else:
                b_status, available = "", None
        else:
            attempted, b_status, available = None, None, None

        visits = attended.get(sid, [])
        is_attended = bool(visits)
        attended_slot = visits[0]["slot"] if visits else ""
        recorded_class = visits[0]["class_id"] if visits else ""
        follow = any(
            (v["class_id"] and v["class_id"] != stu["class_id"])
            or (v["slot"] and class_slot and v["slot"] != class_slot)
            for v in visits
        )

        students.append({
            "student_id": sid, "school": stu["school"], "class_id": stu["class_id"],
            "arm": arm, "venue": alloc.get("venue", ""), "slot": class_slot,
            "invite_received": received if received is not None else "",
            "invite_misrouted": misrouted if misrouted is not None else "",
            "booking_attempted": attempted if attempted is not None else "",
            "booking_status": b_status if b_status is not None else "",
            "slot_available": available if available is not None else "",
            "attended": is_attended,
            "attended_slot": attended_slot,
            "attendance_class_recorded": recorded_class,
            "cross_class_follow": follow,
            "quiz_baseline": quiz_scores.get(sid, {}).get(BASELINE_WAVE),
            "quiz_endline": quiz_scores.get(sid, {}).get(ENDLINE_WAVE),
            "quiz_endline_answered": quiz_answered.get(sid, False),
        })

    return Panel(students=students, sessions=sessions,
                 unmatched_attendance=unmatched_attendance,
                 unmatched_quiz=unmatched_quiz, issues=issues)


def _check_fcfs(bookings: list[dict], sessions: dict[str, dict], roster: dict) -> list[str]:
    """按 requested_at 重放先到先得，核对场馆给的 status 是否与容量一致。"""
    issues: list[str] = []
    by_slot: dict[str, list[dict]] = {}
    for row in bookings:
        if row["status"] in ("confirmed", "rejected_full") and row["requested_at"]:
            by_slot.setdefault(row["slot"], []).append(row)
        elif row["status"] in ("confirmed", "rejected_full"):
            issues.append(f"bookings.csv 第{row['__line__']}行: 缺 requested_at，无法核对先到先得顺序")
    for slot, rows in by_slot.items():
        cap = (sessions.get(slot) or {}).get("capacity")
        if cap is None:
            continue
        rows.sort(key=lambda r: (r["requested_at"], r["booking_id"]))
        confirmed = 0
        for row in rows:
            available = confirmed < cap
            if row["status"] == "confirmed":
                if not available:
                    issues.append(
                        f"bookings.csv 第{row['__line__']}行: 场次 {slot} 已满仍确认 "
                        f"(booking_id={row['booking_id']})，请与场馆核对"
                    )
                confirmed += 1
            elif row["status"] == "rejected_full" and available:
                issues.append(
                    f"bookings.csv 第{row['__line__']}行: 场次 {slot} 尚有空位却记为满额拒绝 "
                    f"(booking_id={row['booking_id']})，请与场馆核对"
                )
    return issues
