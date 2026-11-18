"""把分析结果渲染为中文 Markdown 报告。"""
from __future__ import annotations

import math


def _fmt(x, digits=3, na="—"):
    if x is None:
        return na
    if isinstance(x, float) and math.isnan(x):
        return na
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def _pct(x):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.1%}"


def effect_block(res: dict) -> str:
    lines = [f"#### {res.get('label') or '效果估计'}（{res['treat']} vs {res['control']}）", ""]
    if "error" in res:
        lines.append(f"- 无法估计：{res['error']}")
        return "\n".join(lines)
    lines += [
        f"- 样本：{res['n']} 名学生（处理 {res['n_treat']} / 对照 {res['n_control']}），"
        f"{res['clusters']} 个班、{res['schools']} 所学校",
        f"- 组间均值：处理 {_fmt(res['mean_treat'])}，对照 {_fmt(res['mean_control'])}",
        f"- **ITT 估计（校内比较）：{_fmt(res['estimate'])}**",
        f"- 班级聚类稳健标准误：{_fmt(res['se_cluster'])}"
        f"（把学生当独立个体的朴素标准误 {_fmt(res['se_naive_independent'])}，仅供对照，不可取）",
        f"- 95% 置信区间：[{_fmt(res['ci_low'])}, {_fmt(res['ci_high'])}]，"
        f"t={_fmt(res['t'], 2)}，p={_fmt(res['p_value'], 4)}（df={res['df']}）",
    ]
    ri = res.get("randomization_inference")
    if ri:
        kind = "精确枚举" if ri.get("exact") else "蒙特卡洛"
        lines.append(f"- 随机化推断（校内班级置换，{kind} {ri.get('n_perms')} 次）："
                     f"p={_fmt(ri.get('p_value'), 4)}")
        if ri.get("note"):
            lines.append(f"  - {ri['note']}")
    for w in res.get("warnings", []):
        lines.append(f"- ⚠ {w}")
    return "\n".join(lines)


def sensitivity_block(sens: dict) -> str:
    lines = ["#### 期末小测缺测敏感性", ""]
    if "error" in sens.get("primary", {}):
        return "\n".join(lines + ["- 小测主分析无法估计，敏感性从略"])
    lines.append(f"- 缺测 {sens['n_missing']} / {sens['n_scoped']} 人；未测者不算答错，主分析只用已测者")
    for key, name in (("bound_low", "最坏情形"), ("bound_high", "最好情形")):
        b = sens.get(key, {})
        if b and "error" not in b:
            lines.append(
                f"- {name}：估计 {_fmt(b['estimate'])}，"
                f"95% CI [{_fmt(b['ci_low'])}, {_fmt(b['ci_high'])}]")
    tip = sens.get("tipping", {})
    for key, name in (("treat_missing_adverse", "处理组缺测者不利"),
                      ("control_missing_adverse", "对照组缺测者不利")):
        t = tip.get(key)
        if t:
            lines.append(
                f"- 临界点（{name}）：失去统计显著需 Δ={t['delta_lose_significance']} 分，"
                f"结论变号需 Δ={t['delta_sign_flip']} 分")
    return "\n".join(lines)


def analysis_report(results: list[dict], sens: dict | None, treat: str, control: str) -> str:
    parts = [f"# 邀请效果分析（{treat} vs {control}）", ""]
    for res in results:
        parts.append(effect_block(res))
        parts.append("")
    if sens:
        parts.append(sensitivity_block(sens))
        parts.append("")
    return "\n".join(parts)


def capacity_report(sessions: list[dict], supply: dict) -> str:
    lines = ["# 场次容量与席位压力", "",
             "| 场次 | 场馆 | 容量 | 需求 | 每生席位 | 班数 | 校数 | 超员 | 匹配签到 | 未识别签到 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sessions:
        lines.append(
            f"| {r['slot']} | {r['venue']} | {_fmt(r['capacity'])} | {r['demand']} | "
            f"{_fmt(r['seats_per_student'], 2)} | {r['n_classes']} | {r['n_schools']} | "
            f"{'是' if r['oversubscribed'] else '否'} | {r['matched_checkins']} | "
            f"{r['unmatched_checkins']} |")
    lines += ["",
              f"- 试验最紧张场次每生席位：{_fmt(supply['min_seats_per_student'], 2)}",
              f"- 试验最大单场次班数：{supply['max_classes_per_session']}；"
              f"最大单场次校数：{supply['max_schools_per_session']}",
              "- 效果估计只在上述供给条件下成立；扩场方案须另行核对，不得按平均提升自动放大发放量。"]
    return "\n".join(lines)


def review_report(ev: dict) -> str:
    lines = [f"# 扩场复核：{ev['school']}", "",
             f"- 工具版本：{ev['tool_version']}；输入指纹：{ev['inputs_hash']}",
             f"- 对比口径：{ev['treat_arm']} vs {ev['control_arm']}；学生 {ev['n_students']} 人",
             "", "## 建议", "",
             f"**{ev['recommendation']}**", ""]
    if ev["reasons"]:
        lines += ["理由："] + [f"- {r}" for r in ev["reasons"]]
    if ev["warnings"]:
        lines += ["", "警告："] + [f"- {w}" for w in ev["warnings"]]

    a = ev["assignment"]
    lines += ["", "## 分配证据", ""]
    for arm, cell in a["cells"].items():
        lines.append(f"- {arm}：{cell['classes']} 个班、{cell['students']} 名学生")
    lines.append(f"- 校内两组可比：{'是' if a['has_within_school_comparison'] else '否'}")
    lines.append(f"- 实际发放记录：{'已提供' if a['invite_log_present'] else '未提供（按假定处理）'}")
    lines.append(f"- 发错邀请：{a['misrouted_count']} 人（{_pct(a['misrouted_rate'])}）；"
                 f"整班发错：{'是' if a['whole_class_misroute'] else '否'}")

    c = ev["coverage"]
    lines += ["", "## 样本覆盖", "",
              f"- 签到可匹配率（全馆口径）：{_pct(c['attendance_match_rate'])}"
              f"（未识别签到 {c['unmatched_attendance_total']} 条，不凭场次分班）",
              f"- 到馆 {c['attended_students']} 人；到馆者小测作答率："
              f"{_pct(c['quiz_answered_rate_among_attended'])}",
              f"- 预约记录：{'已提供' if c['bookings_present'] else '未提供'}；"
              f"场次表：{'已提供' if c['sessions_present'] else '未提供'}"]

    cap = ev["capacity"]
    lines += ["", "## 席位压力", ""]
    for d in cap["session_detail"]:
        lines.append(
            f"- {d['slot']}：容量 {_fmt(d['capacity'])}，需求 {d['demand']}，"
            f"每生席位 {_fmt(d['seats_per_student'], 2)}，{d['n_classes']} 个班共用"
            f"{'，**超员**' if d['oversubscribed'] else ''}")
    if "booking" in cap:
        b = cap["booking"]
        lines.append(f"- 预约：尝试 {b['attempted']}，确认 {b['confirmed']}，"
                     f"满额被拒 {b['rejected_full']}（{_pct(b['rejection_rate'])}）")
    lines.append(f"- 跨班跟随 {cap['cross_class_follows']} 人（按原分组保留）")

    lines += ["", "## 效果结论", ""]
    lines.append(effect_block(ev["effects"]["participation"]))
    lines.append("")
    lines.append(effect_block(ev["effects"]["quiz_endline"]))
    lines.append("")
    lines.append(effect_block(ev["effects"]["quiz_tested"]))
    lines.append("")
    lines.append(sensitivity_block(ev["effects"]["quiz_sensitivity"]))

    bal = ev.get("balance", {})
    if bal:
        lines += ["", "## 期初平衡", ""]
        for arm, v in bal.items():
            lines.append(f"- {arm}：期初均分 {_fmt(v['baseline_mean'])}（n={v['n']}）")

    plan = ev.get("plan_check")
    lines += ["", "## 扩场方案核对", ""]
    if plan is None:
        lines.append("- 未提交扩场方案")
    else:
        lines.append(f"- 基准：试验最紧张每生席位 {_fmt(plan['benchmark_seats_per_student'], 2)}，"
                     f"最大班级重叠 {plan['benchmark_max_class_overlap']}")
        for item in plan["checked_sessions"]:
            lines.append(f"- 拟用 {item['slot']}：每生席位 {_fmt(item['seats_per_student'], 2)}，"
                         f"{item['expected_classes']} 个班")
        for v in plan["violations"]:
            lines.append(f"- ❌ {v}")
        if plan["ok"]:
            lines.append("- ✅ 拟用场次在试验比较支持的供给条件内")
    return "\n".join(lines)
