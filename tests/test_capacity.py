"""容量与干扰：场次需求、先到先得核对、扩场方案门槛。"""
import tempfile
import unittest
from pathlib import Path

import helpers
from tourtrial import capacity


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, **kw):
        helpers.make_dir(self.root, **kw)
        return helpers.load(self.root)

    def test_shared_session_demand_and_oversubscription(self):
        s, a, at, q = helpers.base_tables(n_per_class=10)
        # 两班共用 周六上午，容量 15 < 需求 20
        a[0][6] = 15
        a[1][6] = 15
        data, pnl = self.load(students=s, allocation=a, attendance=at, quiz=q)
        sessions = {r["slot"]: r for r in capacity.session_metrics(data, pnl)}
        sess = sessions["周六上午"]
        self.assertEqual(sess["capacity"], 15)
        self.assertEqual(sess["demand"], 20)
        self.assertTrue(sess["oversubscribed"])
        self.assertEqual(sess["n_classes"], 2)

    def test_fcfs_replay_flags_inconsistent_bookings(self):
        # 容量 1：两笔都 confirmed -> 第二笔超额确认应被点名
        s, a, at, q = helpers.base_tables()
        a[0][6] = 1
        a[1][6] = 1
        bookings = [["B1", "A101", "周六上午", "2026-05-01 09:00", "confirmed"],
                    ["B2", "A201", "周六上午", "2026-05-01 09:05", "confirmed"]]
        _, pnl = self.load(students=s, allocation=a, attendance=at, quiz=q, bookings=bookings)
        self.assertTrue(any("已满仍确认" in m for m in pnl.issues))

    def test_rejection_recorded_without_moving_arm(self):
        bookings = [["B1", "A101", "周六上午", "2026-05-01 09:00", "rejected_full"]]
        _, pnl = self.load(bookings=bookings)
        stu = pnl.get("A101")
        self.assertEqual(stu["arm"], "诗词互动")
        self.assertEqual(stu["booking_status"], "rejected_full")
        self.assertIs(stu["slot_available"], False)


class PlanCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        helpers.make_dir(self.root)
        _, self.pnl = helpers.load(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, rows, school="甲校"):
        plan = [{"school": r[0], "venue": r[1], "slot": r[2], "seat_capacity": r[3],
                 "expected_classes": r[4], "expected_students": r[5]} for r in rows]
        return capacity.check_expansion_plan(plan, self.pnl, school)

    def test_good_plan_passes(self):
        # 试验基准：每生席位 30/20=1.5，最大重叠 2 个班
        res = self.check([["甲校", "东厅", "周日上午", 30, 2, 20]])
        self.assertTrue(res["ok"], res["violations"])

    def test_reusing_trial_session_is_returned(self):
        res = self.check([["甲校", "西廊", "周六上午", 40, 2, 20]])
        self.assertFalse(res["ok"])
        self.assertTrue(any("沿用" in v for v in res["violations"]))

    def test_thinner_capacity_than_trial_is_returned(self):
        res = self.check([["甲校", "东厅", "周日上午", 20, 2, 20]])  # 每生席位 1.0 < 1.5
        self.assertFalse(res["ok"])
        self.assertTrue(any("接待量" in v for v in res["violations"]))

    def test_heavier_class_overlap_than_trial_is_returned(self):
        res = self.check([["甲校", "东厅", "周日上午", 90, 4, 40]])  # 4 班共用 > 试验最大 2
        self.assertFalse(res["ok"])
        self.assertTrue(any("重叠" in v for v in res["violations"]))

    def test_cross_school_sharing_is_returned(self):
        rows = [["甲校", "东厅", "周日上午", 60, 2, 20],
                ["乙校", "东厅", "周日上午", 60, 2, 20]]  # 两校拟共用同一时段
        res = self.check(rows, school="甲校")
        self.assertFalse(res["ok"])
        self.assertTrue(any("共享" in v for v in res["violations"]))


if __name__ == "__main__":
    unittest.main()
