"""场次容量、席位压力与共享干扰。

试验中的邀请效果只在"原供给条件"下成立：同校的班挤同一批场次、
先到先得可能让先收到邀请的人占掉后来者的名额。本模块把这些供给条件
量化，供扩场方案核对：拟用场次的接待量或班级重叠若超出试验支持范围，
方案应退回待复核，而不是按平均提升自动放大发放量。
"""
from __future__ import annotations

from .io import TrialData
from .panel import Panel


def session_metrics(data: TrialData, panel: Panel) -> list[dict]:
    """每个场次一行：容量、需求、签到、预约、共享情况。"""
    rows = []
    for slot, sess in sorted(panel.sessions.items()):
        classes = sess["classes"]
        demand = sum(1 for s in panel.students
                     if (s["school"], s["class_id"]) in classes)
        matched = sum(1 for s in panel.students if s["attended"] and s["attended_slot"] == slot)
        unmatched = sum(1 for r in panel.unmatched_attendance if r["slot"] == slot)
        cap = sess["capacity"]
        row = {
            "slot": slot, "venue": sess["venue"], "capacity": cap,
            "n_classes": len(classes), "n_schools": len(sess["schools"]),
            "schools": sess["schools"], "demand": demand,
            "seats_per_student": (cap / demand) if cap and demand else None,
            "oversubscribed": bool(cap is not None and demand > cap),
            "matched_checkins": matched, "unmatched_checkins": unmatched,
        }
        if data.bookings:
            books = [b for b in data.bookings if b["slot"] == slot and b["status"] != "cancelled"]
            row["booking_attempts"] = len(books)
            row["booking_confirmed"] = sum(1 for b in books if b["status"] == "confirmed")
            row["booking_rejected_full"] = sum(1 for b in books if b["status"] == "rejected_full")
        rows.append(row)
    return rows


def school_capacity(panel: Panel, school: str) -> dict:
    """单个学校的席位压力概况。"""
    students = panel.by_school(school)
    n = len(students)
    attended = sum(1 for s in students if s["attended"])
    out = {
        "school": school, "students": n, "attended": attended,
        "attendance_rate": attended / n if n else None,
        "sessions": sorted({s["slot"] for s in students if s["slot"]}),
        "cross_class_follows": sum(1 for s in students if s["cross_class_follow"]),
        "invite_misrouted": sum(1 for s in students if s["invite_misrouted"] is True),
    }
    attempted = [s for s in students if s["booking_attempted"] is True]
    if any(s["booking_attempted"] != "" for s in students):
        confirmed = sum(1 for s in students if s["booking_status"] == "confirmed")
        rejected = sum(1 for s in students if s["booking_status"] == "rejected_full")
        out["booking"] = {
            "attempted": len(attempted), "confirmed": confirmed,
            "rejected_full": rejected,
            "rejection_rate": rejected / len(attempted) if attempted else None,
        }
    # 该校班级所在场次的超员情况
    slots = []
    for slot in out["sessions"]:
        sess = panel.sessions.get(slot, {})
        cap, classes = sess.get("capacity"), sess.get("classes", [])
        demand = sum(1 for s in panel.students if (s["school"], s["class_id"]) in classes)
        slots.append({
            "slot": slot, "capacity": cap, "demand": demand,
            "n_classes": len(classes), "n_schools": len(sess.get("schools", [])),
            "oversubscribed": bool(cap is not None and demand > cap),
            "seats_per_student": (cap / demand) if cap and demand else None,
        })
    out["session_detail"] = slots
    return out


def trial_supply_summary(panel: Panel) -> dict:
    """试验实际供给条件：效果估计只在这个供给环境下成立。"""
    seats, overlaps, school_shares = [], [], []
    for slot, sess in panel.sessions.items():
        cap = sess["capacity"]
        demand = sum(1 for s in panel.students
                     if (s["school"], s["class_id"]) in sess["classes"])
        if cap and demand:
            seats.append(cap / demand)
        overlaps.append(len(sess["classes"]))
        school_shares.append(len(sess["schools"]))
    return {
        "min_seats_per_student": min(seats) if seats else None,
        "max_classes_per_session": max(overlaps) if overlaps else 0,
        "max_schools_per_session": max(school_shares) if school_shares else 0,
    }


# ---------- 扩场方案核对 ----------

PLAN_COLUMNS = ["school", "venue", "slot", "seat_capacity", "expected_classes", "expected_students"]


def check_expansion_plan(plan_rows: list[dict], panel: Panel,
                         school: str, tolerance: float = 0.0) -> dict:
    """核对某校拟扩场方案是否落在试验比较支持的供给条件内。

    规则（违反即"退回待复核"）：
    1. 不得直接沿用试验中的场次；
    2. 每生席位不得低于试验中该校（或总体）最紧张场次的水平（容差 tolerance）；
    3. 单场次班级重叠数不得超出试验中观察到的最大值；
    4. 不得与其他学校的拟用场次共享席位（试验未覆盖跨校共享的新情形）。
    """
    supply = trial_supply_summary(panel)
    school_caps = school_capacity(panel, school)
    school_seats = [d["seats_per_student"] for d in school_caps["session_detail"]
                    if d["seats_per_student"]]
    benchmark_seats = min(school_seats) if school_seats else supply["min_seats_per_student"]
    benchmark_overlap = supply["max_classes_per_session"]
    trial_slots = set(panel.sessions)

    # 跨校共享检查：同一 slot 被多所学校拟用
    slot_owners: dict[str, set] = {}
    for row in plan_rows:
        slot_owners.setdefault(row["slot"], set()).add(row["school"])

    violations: list[str] = []
    warnings: list[str] = []
    checked = []
    for row in plan_rows:
        if row["school"] != school:
            continue
        slot = row["slot"]
        item = {"slot": slot, "venue": row["venue"]}
        try:
            cap = int(row["seat_capacity"])
            n_students = int(row["expected_students"])
            n_classes = int(row["expected_classes"])
        except (ValueError, KeyError):
            violations.append(f"方案行 {row}: 容量/人数/班数无法解析")
            continue
        if cap <= 0 or n_students <= 0 or n_classes <= 0:
            violations.append(f"场次 {slot}: 容量、预计人数、预计班数必须为正数")
            continue
        item["seats_per_student"] = cap / n_students
        item["expected_classes"] = n_classes

        if slot in trial_slots:
            violations.append(f"场次 {slot}: 直接沿用了试验中的场次，扩场名单不得照搬")
        if benchmark_seats is not None and cap / n_students < benchmark_seats * (1 - tolerance):
            violations.append(
                f"场次 {slot}: 每生席位 {cap / n_students:.2f} 低于试验最紧张水平 "
                f"{benchmark_seats:.2f}，接待量不在试验比较支持范围内")
        if benchmark_overlap and n_classes > benchmark_overlap:
            violations.append(
                f"场次 {slot}: 预计 {n_classes} 个班共用，超出试验观察到的最大重叠 "
                f"{benchmark_overlap} 个班")
        if len(slot_owners.get(slot, set())) > 1:
            owners = "、".join(sorted(slot_owners[slot]))
            violations.append(f"场次 {slot}: 与 {owners} 拟用的场次共享席位，试验未覆盖该情形")
        checked.append(item)

    if not checked:
        warnings.append(f"方案文件中没有学校 {school} 的行")

    return {
        "school": school, "checked_sessions": checked,
        "benchmark_seats_per_student": benchmark_seats,
        "benchmark_max_class_overlap": benchmark_overlap,
        "violations": violations, "warnings": warnings,
        "ok": not violations,
    }
