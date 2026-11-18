"""估计口径：校内比较、班级聚类不确定性与随机化推断、缺测敏感性。"""
import math
import unittest

from tourtrial import effects
from tourtrial.panel import Panel


def make_students(spec):
    """spec: [(school, class_id, arm, [y...]), ...] -> 学生字典列表（attended=y）。"""
    students = []
    i = 0
    for school, cls, arm, ys in spec:
        for y in ys:
            i += 1
            students.append({
                "student_id": f"S{i:04d}", "school": school, "class_id": cls,
                "arm": arm, "venue": "", "slot": "",
                "invite_received": "", "invite_misrouted": "",
                "booking_attempted": "", "booking_status": "", "slot_available": "",
                "attended": bool(y), "attended_slot": "", "attendance_class_recorded": "",
                "cross_class_follow": False,
                "quiz_baseline": None, "quiz_endline": None, "quiz_endline_answered": False,
            })
    return students


def panel(students):
    return Panel(students=students, sessions={})


class EstimateTests(unittest.TestCase):
    def test_known_effect_is_recovered(self):
        spec = [("甲校", "A1", "诗词互动", [1] * 10), ("甲校", "A2", "常规导览", [0] * 10),
                ("乙校", "B1", "诗词互动", [1] * 10), ("乙校", "B2", "常规导览", [0] * 10)]
        pnl = panel(make_students(spec))
        res = effects.estimate_itt(pnl, effects.outcome_participation, "诗词互动", "常规导览")
        self.assertAlmostEqual(res["estimate"], 1.0)
        self.assertEqual(res["clusters"], 4)

    def test_cluster_se_reflects_class_level_assignment(self):
        # 班内高度相关（全班同上/同下），班级才是分配单位：聚类 SE 必须大于朴素 SE
        spec = []
        treat_means = [0.9, 0.5, 0.85, 0.55, 0.8, 0.6]
        control_means = [0.1, 0.5, 0.15, 0.45, 0.2, 0.4]
        for i, (tm, cm) in enumerate(zip(treat_means, control_means)):
            spec.append((f"校{i}", f"T{i}", "诗词互动",
                         [1] * round(tm * 20) + [0] * (20 - round(tm * 20))))
            spec.append((f"校{i}", f"C{i}", "常规导览",
                         [1] * round(cm * 20) + [0] * (20 - round(cm * 20))))
        pnl = panel(make_students(spec))
        res = effects.estimate_itt(pnl, effects.outcome_participation, "诗词互动", "常规导览")
        self.assertGreater(res["se_cluster"], 1.5 * res["se_naive_independent"])

    def test_exact_randomization_inference(self):
        # 3 校各 1 处理班 + 1 对照班：共 2^3=8 种置换；处理班全到、对照班全不到
        spec = []
        for i in range(3):
            spec.append((f"校{i}", f"T{i}", "诗词互动", [1] * 10))
            spec.append((f"校{i}", f"C{i}", "常规导览", [0] * 10))
        pnl = panel(make_students(spec))
        res = effects.estimate_itt(pnl, effects.outcome_participation, "诗词互动", "常规导览")
        ri = res["randomization_inference"]
        self.assertTrue(ri["exact"])
        self.assertEqual(ri["n_perms"], 8)
        self.assertAlmostEqual(ri["p_value"], 0.25)  # 最极端情形：2/8

    def test_students_are_not_treated_as_independent(self):
        # 同一数据下若误把学生当独立随机，会得到过小的不确定度
        spec = []
        for i in range(4):
            spec.append((f"校{i}", f"T{i}", "诗词互动", [1] * 25))
            spec.append((f"校{i}", f"C{i}", "常规导览", [0] * 25))
        pnl = panel(make_students(spec))
        res = effects.estimate_itt(pnl, effects.outcome_participation, "诗词互动", "常规导览")
        self.assertIn("clusters", res)
        self.assertEqual(res["clusters"], 8)  # 有效独立信息是 8 个班，不是 200 名学生


class MissingnessTests(unittest.TestCase):
    def make_quiz_panel(self, missing_share_treat=0.3, missing_share_control=0.3):
        students = []
        i = 0
        for school in ("甲校", "乙校"):
            for cls, arm, score, miss in (("T", "诗词互动", 8.0, missing_share_treat),
                                          ("C", "常规导览", 6.0, missing_share_control)):
                for k in range(20):
                    i += 1
                    tested = k >= round(20 * miss)
                    students.append({
                        "student_id": f"S{i:04d}", "school": school,
                        "class_id": f"{school}{cls}", "arm": arm,
                        "venue": "", "slot": "",
                        "invite_received": "", "invite_misrouted": "",
                        "booking_attempted": "", "booking_status": "", "slot_available": "",
                        "attended": True, "attended_slot": "",
                        "attendance_class_recorded": "", "cross_class_follow": False,
                        "quiz_baseline": 5.0,
                        "quiz_endline": score if tested else None,
                        "quiz_endline_answered": tested,
                    })
        return panel(students)

    def test_untested_not_counted_as_wrong(self):
        pnl = self.make_quiz_panel()
        res = effects.estimate_itt(pnl, effects.outcome_quiz_endline, "诗词互动", "常规导览")
        self.assertEqual(res["n"], 56)  # 80 人中 24 人缺测，不计入也不算 0 分
        self.assertAlmostEqual(res["estimate"], 2.0)

    def test_bounds_bracket_primary(self):
        pnl = self.make_quiz_panel()
        sens = effects.quiz_missingness_sensitivity(pnl, "诗词互动", "常规导览")
        low = sens["bound_low"]["estimate"]
        high = sens["bound_high"]["estimate"]
        self.assertLess(low, sens["primary"]["estimate"])
        self.assertGreater(high, sens["primary"]["estimate"])
        self.assertLess(low, 0)   # 最坏情形下结论可以反转，必须被看见

    def test_tipping_point_reported(self):
        pnl = self.make_quiz_panel()
        sens = effects.quiz_missingness_sensitivity(pnl, "诗词互动", "常规导览")
        tip = sens["tipping"]["treat_missing_adverse"]["delta_lose_significance"]
        self.assertIsInstance(tip, float)
        self.assertGreater(tip, 0)


if __name__ == "__main__":
    unittest.main()
