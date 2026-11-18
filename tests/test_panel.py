"""事实表：原始分组不可变；实际收到 / 名额 / 参加分别可查；未识别签到不凭场次分班。"""
import tempfile
import unittest
from pathlib import Path

import helpers
from tourtrial import effects


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, **kw):
        helpers.make_dir(self.root, **kw)
        return helpers.load(self.root)

    def test_misrouted_invitation_does_not_move_arm(self):
        invitations = [["A101", "A1", "常规导览", "2026-05-01 08:00"]]  # 发错：应发诗词互动
        _, pnl = self.load(invitations=invitations)
        stu = pnl.get("A101")
        self.assertEqual(stu["arm"], "诗词互动")          # 原始分组不变
        self.assertEqual(stu["invite_received"], "常规导览")  # 实际收到单独记录
        self.assertIs(stu["invite_misrouted"], True)

    def test_cross_class_follow_does_not_move_arm(self):
        s, a, at, q = helpers.base_tables()
        at.append(["E900", "A2", "A101", "周六上午", "09:30", "人工补登"])  # A101 跟 A2 班签到
        _, pnl = self.load(students=s, allocation=a, attendance=at, quiz=q)
        stu = pnl.get("A101")
        self.assertEqual(stu["arm"], "诗词互动")
        self.assertIs(stu["cross_class_follow"], True)
        self.assertIs(stu["attended"], True)

    def test_full_capacity_does_not_move_arm(self):
        bookings = [["B1", "A101", "周六上午", "2026-05-01 09:00", "rejected_full"],
                    ["B2", "A102", "周六上午", "2026-05-01 09:01", "confirmed"]]
        _, pnl = self.load(bookings=bookings)
        rejected = pnl.get("A101")
        self.assertEqual(rejected["arm"], "诗词互动")      # 满额不改变分组
        self.assertIs(rejected["slot_available"], False)   # 名额事实单独可查
        self.assertIs(pnl.get("A102")["slot_available"], True)

    def test_unmatched_checkin_never_assigned_by_slot(self):
        s, a, at, q = helpers.base_tables()
        n_treat_before = None
        at.append(["E901", "A1", "S999", "周六上午", "09:31", "人工补登"])  # 名册查无此人
        at.append(["E902", "A1", "", "周六上午", "09:32", "人工补登"])      # 空 student_id
        _, pnl = self.load(students=s, allocation=a, attendance=at, quiz=q)
        self.assertEqual(len(pnl.unmatched_attendance), 2)
        for row in pnl.unmatched_attendance:
            self.assertIn(row["slot"], ("周六上午",))
        # 没有任何学生因这两条签到被记为参加
        attended_ids = {stu["student_id"] for stu in pnl.students if stu["attended"]}
        self.assertNotIn("S999", attended_ids)
        n_treat = sum(1 for stu in pnl.students
                      if stu["arm"] == "诗词互动" and stu["attended"])
        self.assertEqual(n_treat, 16)  # 两个处理班各 8 人，不多不少

    def test_empty_score_is_missing_not_zero(self):
        # 基线数据中 A109（处理班未到馆、期末 answered=false 且分数为空）
        _, pnl = self.load()
        stu = pnl.get("A109")
        self.assertIsNone(stu["quiz_endline"])
        self.assertIs(stu["quiz_endline_answered"], False)
        self.assertIsNone(effects.outcome_quiz_endline(stu))  # 不计入，也不算答错
        tested = pnl.get("A101")
        self.assertIsInstance(tested["quiz_endline"], float)

    def test_three_facts_are_independently_queryable(self):
        bookings = [["B1", "A101", "周六上午", "2026-05-01 09:00", "rejected_full"]]
        invitations = [["A101", "A1", "诗词互动", "2026-05-01 08:00"]]
        _, pnl = self.load(bookings=bookings, invitations=invitations)
        stu = pnl.get("A101")
        self.assertEqual(stu["invite_received"], "诗词互动")  # 收到了
        self.assertIs(stu["slot_available"], False)          # 但没名额
        self.assertIs(stu["attended"], True)                 # 参加与否是第三个事实（基线数据里到馆）

    def test_unknown_quiz_student_not_attributed(self):
        s, a, at, q = helpers.base_tables()
        q.append(["S999", "A1", "期末", "9", "true"])
        _, pnl = self.load(students=s, allocation=a, attendance=at, quiz=q)
        self.assertEqual(len(pnl.unmatched_quiz), 1)
        self.assertTrue(all(stu["student_id"] != "S999" for stu in pnl.students))


if __name__ == "__main__":
    unittest.main()
