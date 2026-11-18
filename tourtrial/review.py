"""扩场复核：为每所拟扩场学校汇总分配证据、样本覆盖、席位压力与结论，
并给出建议（批准扩场 / 退回待复核 / 证据不足-暂缓扩场）。

判断规则（阈值可由 Thresholds 调整）：
- 分配证据：校内须同时具备两组班级；发错邀请率超过阈值或整班发错 -> 证据不足；
  单纯发错一封邀请只记警告，不让有足够证据的学校全部停试。
- 样本覆盖：签到可匹配率、到馆者小测作答率低于阈值 -> 证据不足。
- 席位压力/干扰：拟用场次的接待量或班级重叠超出试验比较支持范围 -> 退回待复核；
  工具只核对门槛，绝不按平均提升自动放大发放量。
"""
from __future__ import annotations

from dataclasses import dataclass

from . import __version__, capacity, effects
from .io import TrialData
from .panel import Panel

APPROVE = "批准扩场"
RETURN = "退回待复核"
INSUFFICIENT = "证据不足-暂缓扩场"
DECISIONS = (APPROVE, RETURN, INSUFFICIENT)


@dataclass
class Thresholds:
    min_classes_per_arm: int = 2        # 校内每组班数低于此值记警告（不确定性大）
    misroute_rate_block: float = 0.05   # 发错邀请比例超过则证据不足
    min_attendance_match_rate: float = 0.8
    min_quiz_answered_rate: float = 0.5  # 到馆者中小测有期末成绩的比例
    capacity_tolerance: float = 0.0     # 每生席位容差


def build_evidence(data: TrialData, panel: Panel, school: str,
                   treat: str, control: str,
                   plan_rows: list[dict] | None = None,
                   thresholds: Thresholds | None = None,
                   ri_draws: int = 4999) -> dict:
    th = thresholds or Thresholds()
    students = panel.by_school(school)
    if not students:
        raise ValueError(f"名册中没有学校 {school} 的学生")

    evidence: dict = {
        "school": school,
        "tool_version": __version__,
        "inputs_hash": data.inputs_hash,
        "treat_arm": treat, "control_arm": control,
        "n_students": len(students),
    }

    # ---- 分配证据 ----
    cells = effects.school_cells(panel, treat, control).get(school, {})
    misrouted = [s for s in students if s["invite_misrouted"] is True]
    whole_class_misroute = _whole_class_misroute(students)
    invite_missing = sum(
        1 for s in students
        if data.invitations is not None and s["arm"] == treat and s["invite_received"] == "")
    evidence["assignment"] = {
        "cells": cells,
        "has_within_school_comparison": bool(
            cells.get(treat, {}).get("classes") and cells.get(control, {}).get("classes")),
        "invite_log_present": data.invitations is not None,
        "misrouted_count": len(misrouted),
        "misrouted_rate": len(misrouted) / len(students) if students else 0.0,
        "whole_class_misroute": whole_class_misroute,
        "invite_missing_count": invite_missing,
    }

    # ---- 样本覆盖 ----
    attended = [s for s in students if s["attended"]]
    quiz_answered = sum(1 for s in attended if s["quiz_endline_answered"])
    evidence["coverage"] = {
        "attendance_rows_total": len(data.attendance),
        "unmatched_attendance_total": len(panel.unmatched_attendance),
        "attendance_match_rate": _safe_div(
            len(data.attendance) - len(panel.unmatched_attendance), len(data.attendance)),
        "attended_students": len(attended),
        "quiz_answered_among_attended": quiz_answered,
        "quiz_answered_rate_among_attended": _safe_div(quiz_answered, len(attended)),
        "bookings_present": data.bookings is not None,
        "sessions_present": data.sessions is not None,
    }

    # ---- 席位压力 ----
    evidence["capacity"] = capacity.school_capacity(panel, school)
    evidence["trial_supply"] = capacity.trial_supply_summary(panel)

    # ---- 效果结论（跨校汇总 ITT + 该校描述）----
    evidence["effects"] = {
        "participation": effects.estimate_itt(
            panel, effects.outcome_participation, treat, control,
            label="到馆参与率", ri_draws=ri_draws),
        "quiz_endline": effects.estimate_itt(
            panel, effects.outcome_quiz_endline, treat, control,
            label="期末小测（仅已测）", ri_draws=ri_draws),
        "quiz_tested": effects.estimate_itt(
            panel, effects.outcome_quiz_tested, treat, control,
            label="期末小测作答率", ri_draws=ri_draws),
        "quiz_sensitivity": effects.quiz_missingness_sensitivity(panel, treat, control),
        "school_descriptive": _school_descriptive(students, treat, control),
    }

    # ---- 期初平衡（随机分配证据之一）----
    evidence["balance"] = _baseline_balance(students, treat, control)

    # ---- 扩场方案核对 ----
    if plan_rows is not None:
        evidence["plan_check"] = capacity.check_expansion_plan(
            plan_rows, panel, school, tolerance=th.capacity_tolerance)
    else:
        evidence["plan_check"] = None

    recommendation, reasons, warnings = recommend(evidence, th)
    evidence["recommendation"] = recommendation
    evidence["reasons"] = reasons
    evidence["warnings"] = warnings
    return evidence


def recommend(evidence: dict, th: Thresholds | None = None):
    th = th or Thresholds()
    reasons: list[str] = []
    warnings: list[str] = []
    insufficient = False

    a = evidence["assignment"]
    if not a["has_within_school_comparison"]:
        insufficient = True
        reasons.append("校内缺少可比较的组别（某一版本邀请没有班级），无法作校内比较")
    for arm, cell in a["cells"].items():
        if cell["classes"] < th.min_classes_per_arm:
            warnings.append(f"组别 {arm} 在校内只有 {cell['classes']} 个班，不确定性较大")
    if not a["invite_log_present"]:
        warnings.append("未提供实际发放记录，'实际收到什么'按假定处理，建议补录 invitations.csv")
    if a["whole_class_misroute"]:
        insufficient = True
        reasons.append("存在整班发错邀请，实际发放与随机分配系统性偏离")
    elif a["misrouted_rate"] > th.misroute_rate_block:
        insufficient = True
        reasons.append(
            f"发错邀请比例 {a['misrouted_rate']:.1%} 超过阈值 {th.misroute_rate_block:.0%}")
    elif a["misrouted_count"] > 0:
        warnings.append(
            f"有 {a['misrouted_count']} 名学生发错邀请（比例低于阈值），按原分组保留，记为警告")
    if a.get("invite_missing_count"):
        warnings.append(
            f"处理组有 {a['invite_missing_count']} 名学生没有发放记录，请核对是否漏发")

    c = evidence["coverage"]
    if c["attendance_match_rate"] is not None and \
            c["attendance_match_rate"] < th.min_attendance_match_rate:
        insufficient = True
        reasons.append(
            f"签到可匹配率 {c['attendance_match_rate']:.1%} 低于阈值 "
            f"{th.min_attendance_match_rate:.0%}（无法识别的签到不得凭场次分班）")
    if c["quiz_answered_rate_among_attended"] is not None and \
            c["quiz_answered_rate_among_attended"] < th.min_quiz_answered_rate:
        insufficient = True
        reasons.append(
            f"到馆者小测作答率 {c['quiz_answered_rate_among_attended']:.1%} 低于阈值 "
            f"{th.min_quiz_answered_rate:.0%}，小测结论对缺测假设过于敏感")
    if not c["bookings_present"]:
        warnings.append("未提供预约记录，'有没有可用名额'不可查，建议补录 bookings.csv")

    if insufficient:
        return INSUFFICIENT, reasons, warnings

    plan = evidence.get("plan_check")
    if plan is None:
        reasons.append("尚未提交扩场方案，无法核对拟用场次的接待量与班级重叠")
        return RETURN, reasons, warnings
    if not plan["ok"]:
        reasons.extend(plan["violations"])
        reasons.append("试验比较只说明原供给条件下的效果，拟用场次超出该范围，退回待复核")
        return RETURN, reasons, warnings

    reasons.append("分配证据、样本覆盖与拟用场次供给条件均在试验支持范围内")
    return APPROVE, reasons, warnings


# ---------- 内部小函数 ----------

def _safe_div(a: float, b: float):
    return a / b if b else None


def _whole_class_misroute(students: list[dict]) -> bool:
    by_class: dict[str, list] = {}
    for s in students:
        if s["invite_misrouted"] != "":
            by_class.setdefault(s["class_id"], []).append(s["invite_misrouted"] is True)
    return any(flags and all(flags) for flags in by_class.values())


def _school_descriptive(students: list[dict], treat: str, control: str) -> dict:
    out = {}
    for arm in (treat, control):
        group = [s for s in students if s["arm"] == arm]
        if not group:
            continue
        attended = [s for s in group if s["attended"]]
        scores = [s["quiz_endline"] for s in group if s["quiz_endline"] is not None]
        out[arm] = {
            "students": len(group),
            "attendance_rate": _safe_div(len(attended), len(group)),
            "quiz_endline_mean": _safe_div(sum(scores), len(scores)) if scores else None,
            "quiz_answered": len(scores),
        }
    return out


def _baseline_balance(students: list[dict], treat: str, control: str) -> dict:
    out = {}
    for arm in (treat, control):
        scores = [s["quiz_baseline"] for s in students
                  if s["arm"] == arm and s["quiz_baseline"] is not None]
        out[arm] = {"n": len(scores),
                    "baseline_mean": _safe_div(sum(scores), len(scores)) if scores else None}
    return out
