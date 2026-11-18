"""复核建议与签发治理：单封错发不停试、整班错发证据不足、方案门槛、台账只增不改。"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

import helpers
from tourtrial import decisions, review


def read_plan(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, school="甲校", plan_rows=None, **kw):
        helpers.make_dir(self.root, **kw)
        data, pnl = helpers.load(self.root)
        plan = None
        if plan_rows is not None:
            plan_path = helpers.write_plan(self.root, plan_rows)
            plan = read_plan(plan_path)
        return review.build_evidence(data, pnl, school, "诗词互动", "常规导览",
                                     plan_rows=plan, ri_draws=199)

    GOOD_PLAN = [["甲校", "东厅", "周日上午", 30, 2, 20]]

    def test_good_evidence_and_plan_approves(self):
        ev = self.build(plan_rows=self.GOOD_PLAN)
        self.assertEqual(ev["recommendation"], review.APPROVE)

    def test_missing_plan_returns_for_review(self):
        ev = self.build()
        self.assertEqual(ev["recommendation"], review.RETURN)

    def test_bad_plan_returns_for_review(self):
        ev = self.build(plan_rows=[["甲校", "西廊", "周六上午", 30, 2, 20]])  # 沿用试验场次
        self.assertEqual(ev["recommendation"], review.RETURN)
        self.assertTrue(any("沿用" in r for r in ev["reasons"]))

    def test_single_misrouted_invitation_does_not_halt(self):
        invitations = [["A101", "A1", "常规导览", "2026-05-01 08:00"]]  # 仅一封发错
        ev = self.build(plan_rows=self.GOOD_PLAN, invitations=invitations)
        self.assertEqual(ev["recommendation"], review.APPROVE)
        self.assertEqual(ev["assignment"]["misrouted_count"], 1)
        self.assertTrue(any("发错" in w for w in ev["warnings"]))

    def test_whole_class_misroute_is_insufficient(self):
        # A1 班 10 人全部发错 -> 整班错发，分配证据不再可信
        invitations = [[f"A1{i:02d}", "A1", "常规导览", "2026-05-01 08:00"] for i in range(1, 11)]
        ev = self.build(plan_rows=self.GOOD_PLAN, invitations=invitations)
        self.assertEqual(ev["recommendation"], review.INSUFFICIENT)
        self.assertTrue(ev["assignment"]["whole_class_misroute"])

    def test_low_attendance_match_rate_is_insufficient(self):
        s, a, at, q = helpers.base_tables()
        # 追加大量无法识别的签到，把可匹配率压到 80% 以下
        for i in range(20):
            at.append([f"E9{i:02d}", "A1", f"X{i:03d}", "周六上午", "09:30", "人工补登"])
        ev = self.build(plan_rows=self.GOOD_PLAN,
                        students=s, allocation=a, attendance=at, quiz=q)
        self.assertEqual(ev["recommendation"], review.INSUFFICIENT)
        self.assertTrue(any("签到" in r for r in ev["reasons"]))

    def test_no_auto_scaling_from_average_lift(self):
        # 工具只核对门槛，绝不在建议中给出"按平均提升放大发放量"的结论
        ev = self.build(plan_rows=self.GOOD_PLAN)
        self.assertNotIn("放大", json.dumps(ev, ensure_ascii=False))
        self.assertNotIn("倍增", json.dumps(ev, ensure_ascii=False))


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "decisions.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, school, decision, note=""):
        ev = {"recommendation": decision, "reasons": ["测试"], "warnings": [],
              "inputs_hash": "abc"}
        prev = decisions.latest(self.log, school)
        rec = decisions.make_record(school, decision, ev, reviewer="测试员", note=note,
                                    supersedes=prev["record_id"] if prev else None)
        decisions.append_decision(self.log, rec)
        return rec

    def test_append_and_history(self):
        self._record("甲校", review.RETURN)
        self._record("甲校", review.APPROVE, note="补录小测后重新评估")
        self._record("乙校", review.INSUFFICIENT)
        hist = decisions.history(self.log, "甲校")
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["decision"], review.RETURN)
        self.assertEqual(hist[1]["decision"], review.APPROVE)
        self.assertEqual(hist[1]["supersedes"], hist[0]["record_id"])

    def test_old_records_are_never_rewritten(self):
        first = self._record("甲校", review.RETURN, note="原始决定")
        before = self.log.read_text(encoding="utf-8")
        self._record("甲校", review.APPROVE, note="更正名额后复核")
        after = self.log.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))  # 旧行原样保留
        loaded = decisions.load_decisions(self.log)
        self.assertEqual(loaded[0]["note"], "原始决定")
        self.assertEqual(loaded[0]["record_id"], first["record_id"])

    def test_corrupt_log_is_detected(self):
        self.log.write_text('{"a": 1}\n不是json\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            decisions.load_decisions(self.log)


if __name__ == "__main__":
    unittest.main()
