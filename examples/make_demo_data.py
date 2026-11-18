"""生成一套带"脏数据"的演示试验数据（确定性随机，可重复）。

覆盖的情形：
- 两版邀请（诗词互动 / 常规导览）按班随机分配，同校的班挤同一批场次；
- 莲池小学席位紧张，先到先得，有人满额被拒；
- 栖霞小学有一封邀请发错（孤立事件）；松风小学整班发错（系统性问题）；
- 签到含无法识别记录与一例跨班跟随；
- 小测与到馆分开记录，期末有缺测（空字段）。

用法：
  python3 examples/make_demo_data.py --out examples/demo_data
  python3 examples/make_demo_data.py --out examples/demo_data --backfill   # 补录期末小测
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

RNG = random.Random(20261118)

SCHOOLS = [
    # 校名, 场馆, 班前缀, 每班人数, 上午容量, 下午容量, 邀请发出日
    ("莲池小学", "西廊", "莲", 24, 26, 26, "2026-05-10"),
    ("松风小学", "南院", "松", 24, 60, 60, "2026-05-12"),
    ("望江小学", "东厅", "望", 24, 60, 60, "2026-05-12"),
    ("栖霞小学", "北廊", "栖", 24, 48, 48, "2026-05-12"),
]
ARMS = ["诗词互动", "诗词互动", "常规导览", "常规导览"]  # 四个班依次
TREAT = "诗词互动"


def clip(x):
    return max(0, min(10, int(round(x))))


def generate(backfill: bool = False):
    students, allocation, sessions = [], [], []
    invitations, bookings, attendance, quiz = [], [], [], []
    event_seq = 0
    booking_seq = 0

    for school, venue, prefix, n_cls, cap_am, cap_pm, sent_day in SCHOOLS:
        slot_am = f"周六上午·{venue}"
        slot_pm = f"周六下午·{venue}"
        sessions.append([slot_am, venue, cap_am])
        sessions.append([slot_pm, venue, cap_pm])
        attempts = []  # (requested_at, booking_id, student_id, slot)

        for c in range(4):
            cls = f"{prefix}{'一二三四'[c]}班"
            arm = ARMS[c]
            slot = slot_am if c in (0, 2) else slot_pm  # 同校的班挤同一批场次
            cap = cap_am if c in (0, 2) else cap_pm
            allocation.append([school, cls, n_cls, arm, venue, slot, cap])

            # 实际发放记录：松风小学第一个班整班发错；其余按分配发放
            sent_arm = arm
            if school == "松风小学" and c == 0:
                sent_arm = "常规导览"  # 整班错发
            invitations.append(["", cls, sent_arm, f"{sent_day} 09:00"])

            for i in range(n_cls):
                sid = f"{prefix}{c+1}{i+1:02d}"
                students.append([sid, school, cls])

                # 栖霞小学一封孤立错发：对照班一名学生收到诗词互动
                if school == "栖霞小学" and c == 2 and i == 0:
                    invitations.append([sid, cls, TREAT, f"{sent_day} 09:05"])

                baseline = clip(5 + RNG.gauss(0, 1.2))
                quiz.append([sid, cls, "期初", baseline, "true"])
                latent = clip(baseline + (1.2 if arm == TREAT else 0) + RNG.gauss(0, 1))

                # 预约：处理版邀请更吸引人；先到先得，超容量即满额
                p_attempt = 0.85 if arm == TREAT else 0.55
                if RNG.random() < p_attempt:
                    booking_seq += 1
                    hour = 9 + RNG.randint(0, 30)
                    day = 10 if sent_day.endswith("10") else 12
                    req = f"2026-05-{day + hour // 24} {hour % 24:02d}:{RNG.randint(0,59):02d}"
                    attempts.append((req, f"B{booking_seq:04d}", sid, slot))

                # 期末是否作答先到馆后再定；此处先记下 latent 分数
                students[-1].append(latent)  # 临时挂在行尾，后面写 quiz 用

        # 先到先得重放，决定 confirmed / rejected_full
        caps = {slot_am: cap_am, slot_pm: cap_pm}
        confirmed_count = {slot_am: 0, slot_pm: 0}
        attempts.sort()
        for req, bid, sid, slot in attempts:
            if confirmed_count[slot] < caps[slot]:
                status = "confirmed"
                confirmed_count[slot] += 1
            else:
                status = "rejected_full"
            bookings.append([bid, sid, slot, req, status])

    # 签到与小测（与是否到馆分开记录）
    latent_by_sid = {row[0]: row[3] for row in students}
    class_by_sid = {row[0]: row[2] for row in students}
    slot_by_class = {(row[0], row[1]): row[5] for row in allocation}
    school_by_sid = {row[0]: row[1] for row in students}
    slot_by_sid = {sid: slot_by_class[(school_by_sid[sid], class_by_sid[sid])]
                   for sid in class_by_sid}
    confirmed_sids = [b[1] for b in bookings if b[4] == "confirmed"]
    for sid in confirmed_sids:
        if RNG.random() < 0.9:
            event_seq += 1
            attendance.append([f"E{event_seq:04d}", class_by_sid[sid], sid,
                               slot_by_sid[sid], f"09:{RNG.randint(10,59)}", "入口终端A"])
    # 一例跨班跟随：莲池小学莲一班一名学生跟着莲二班签到
    follow_sid = "莲101"
    event_seq += 1
    attendance.append([f"E{event_seq:04d}", "莲二班", follow_sid, "周六下午·西廊",
                       "14:20", "人工补登"])
    # 两条无法识别的签到：不得凭场次分给任何班
    for k in range(2):
        event_seq += 1
        attendance.append([f"E{event_seq:04d}", "莲一班", f"X{k:03d}", "周六上午·西廊",
                           "09:4%d" % k, "人工补登"])

    attended_sids = {row[2] for row in attendance}
    for row in students:
        sid, _, cls = row[0], row[1], row[2]
        tested = (sid in attended_sids and RNG.random() < 0.9) or RNG.random() < 0.3
        if tested or backfill:
            quiz.append([sid, cls, "期末", latent_by_sid[sid], "true"])
        else:
            quiz.append([sid, cls, "期末", "", "false"])

    # 去掉临时挂在学生行尾的 latent 分数
    students = [row[:3] for row in students]
    return {
        "students": (["student_id", "school", "class_id"], students),
        "allocation": (["school", "class_id", "students", "invitation_arm",
                        "venue", "slot", "seat_capacity"], allocation),
        "sessions": (["slot", "venue", "seat_capacity"], sessions),
        "invitations": (["student_id", "class_id", "invitation_arm", "sent_at"], invitations),
        "bookings": (["booking_id", "student_id", "slot", "requested_at", "status"], bookings),
        "attendance": (["event_id", "class_id", "student_id", "slot", "arrived_at", "source"],
                       attendance),
        "quiz": (["student_id", "class_id", "wave", "score", "answered"], quiz),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--backfill", action="store_true", help="补录全部期末小测")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tables = generate(backfill=args.backfill)
    for name, (header, rows) in tables.items():
        with (out / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)
    n_quiz_missing = sum(1 for r in tables["quiz"][1] if r[2] == "期末" and r[4] == "false")
    print(f"已生成 {out}（{'含补录小测' if args.backfill else '原始'}）："
          f"{len(tables['students'][1])} 名学生，期末小测缺测 {n_quiz_missing} 人")
    print("演示要点：")
    print("  孤立错发学生：栖301（原分组常规导览，实际收到诗词互动）")
    print("  整班错发：松风小学 松一班；跨班跟随：莲101；无法识别签到：X000/X001")


if __name__ == "__main__":
    main()
