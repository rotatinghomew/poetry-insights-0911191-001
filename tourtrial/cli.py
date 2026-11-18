"""命令行入口。

子命令：
  build-panel  生成学生层面事实表（原始分组 / 实际收到 / 名额 / 参加 分别成列）
  show         查看单个学生的三类事实
  analyze      ITT 效果估计（参与率、小测）与缺测敏感性
  capacity     场次容量与席位压力报告
  review       扩场复核证据包与建议
  sign         签发决定（追加台账，旧决定不改）
  history      查看某校签发历史
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import capacity, decisions, effects, io, panel as panel_mod, report, review


def _load(args):
    data = io.load_data(args.data)
    return data, panel_mod.build_panel(data)


def _pick_arms(data, args):
    arms = data.arms
    treat = args.treat or ("诗词互动" if "诗词互动" in arms else (arms[0] if arms else None))
    control = args.control or ("常规导览" if "常规导览" in arms
                               else (arms[1] if len(arms) > 1 else None))
    if not treat or not control or treat == control:
        raise SystemExit(f"无法确定对比组别；数据中的组别为 {arms}，请用 --treat/--control 指定")
    return treat, control


def _print_issues(pnl):
    if pnl.issues:
        print(f"⚠ 数据核查发现 {len(pnl.issues)} 条问题：", file=sys.stderr)
        for msg in pnl.issues:
            print(f"  - {msg}", file=sys.stderr)


def cmd_build_panel(args):
    _, pnl = _load(args)
    _print_issues(pnl)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=panel_mod.PANEL_COLUMNS)
        writer.writeheader()
        for stu in pnl.students:
            writer.writerow({k: stu.get(k, "") for k in panel_mod.PANEL_COLUMNS})
    print(f"已写出 {out}（{len(pnl.students)} 名学生）；"
          f"未识别签到 {len(pnl.unmatched_attendance)} 条、未匹配小测 {len(pnl.unmatched_quiz)} 条，"
          f"均未凭场次补分给任何班")


def cmd_show(args):
    _, pnl = _load(args)
    stu = pnl.get(args.student)
    if stu is None:
        raise SystemExit(f"名册中没有学生 {args.student}")
    def show(key, label):
        v = stu[key]
        print(f"  {label}: {v if v != '' and v is not None else '（未观测）'}")
    print(f"学生 {stu['student_id']}（{stu['school']} {stu['class_id']}）")
    show("arm", "原始分组（不可变）")
    show("invite_received", "实际收到的邀请")
    show("invite_misrouted", "是否发错")
    show("booking_status", "预约结果")
    show("slot_available", "是否有可用名额")
    show("attended", "最终是否参加")
    show("cross_class_follow", "是否跨班跟随")
    show("quiz_endline", "期末小测成绩")


def cmd_analyze(args):
    data, pnl = _load(args)
    _print_issues(pnl)
    treat, control = _pick_arms(data, args)
    results = [
        effects.estimate_itt(pnl, effects.outcome_participation, treat, control,
                             label="到馆参与率", ri_draws=args.ri_draws),
        effects.estimate_itt(pnl, effects.outcome_quiz_endline, treat, control,
                             label="期末小测（仅已测）", ri_draws=args.ri_draws),
        effects.estimate_itt(pnl, effects.outcome_quiz_tested, treat, control,
                             label="期末小测作答率", ri_draws=args.ri_draws),
        effects.estimate_itt(pnl, effects.outcome_quiz_gain, treat, control,
                             label="小测进步分（期末-期初，仅两期均测）", ri_draws=args.ri_draws),
    ]
    sens = effects.quiz_missingness_sensitivity(
        pnl, treat, control, score_min=args.score_min, score_max=args.score_max)
    text = report.analysis_report(results, sens, treat, control)
    payload = {"treat": treat, "control": control, "results": results, "sensitivity": sens}
    _emit(text, payload, args)


def cmd_capacity(args):
    data, pnl = _load(args)
    _print_issues(pnl)
    sessions = capacity.session_metrics(data, pnl)
    supply = capacity.trial_supply_summary(pnl)
    text = report.capacity_report(sessions, supply)
    _emit(text, {"sessions": sessions, "supply": supply}, args)


def _read_plan(path: str | None):
    if not path:
        return None
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def cmd_review(args):
    data, pnl = _load(args)
    _print_issues(pnl)
    treat, control = _pick_arms(data, args)
    plan_rows = _read_plan(args.plan)
    ev = review.build_evidence(data, pnl, args.school, treat, control,
                               plan_rows=plan_rows, ri_draws=args.ri_draws)
    text = report.review_report(ev)
    _emit(text, ev, args)


def cmd_sign(args):
    data, pnl = _load(args)
    _print_issues(pnl)
    treat, control = _pick_arms(data, args)
    plan_rows = _read_plan(args.plan)
    ev = review.build_evidence(data, pnl, args.school, treat, control,
                               plan_rows=plan_rows, ri_draws=args.ri_draws)
    decision = args.decision or ev["recommendation"]
    if decision not in review.DECISIONS:
        raise SystemExit(f"--decision 须为 {review.DECISIONS} 之一")
    if decision != ev["recommendation"] and not args.note:
        print("⚠ 签发决定与工具建议不一致，建议用 --note 说明理由", file=sys.stderr)
    prev = decisions.latest(args.log, args.school)
    record = decisions.make_record(
        school=args.school, decision=decision, evidence=ev,
        reviewer=args.reviewer, note=args.note,
        supersedes=prev["record_id"] if prev else None)
    decisions.append_decision(args.log, record)
    print(f"已签发并追加台账 {args.log}：{args.school} -> {decision}"
          f"（记录 {record['record_id']}）")
    if prev:
        print(f"该校此前决定 {prev['decision']}（记录 {prev['record_id']}）保留不变，"
              f"本记录以 supersedes 指向它")


def cmd_history(args):
    records = decisions.history(args.log, args.school)
    if not records:
        print(f"{args.school} 暂无签发记录")
        return
    for r in records:
        sup = f"，取代 {r['supersedes']}" if r.get("supersedes") else ""
        print(f"[{r['decided_at']}] {r['decision']}（记录 {r['record_id']}{sup}）"
              f" 签发人：{r.get('reviewer') or '—'} 备注：{r.get('note') or '—'}")


def _emit(text, payload, args):
    if getattr(args, "out", None):
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"已写出 {args.out}")
    else:
        print(text)
    if getattr(args, "json", None):
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"已写出 {args.json}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tourtrial", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--data", default="data", help="数据目录（默认 data）")

    p = sub.add_parser("build-panel", help="生成学生层面事实表")
    common(p); p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_build_panel)

    p = sub.add_parser("show", help="查看单个学生的三类事实")
    common(p); p.add_argument("--student", required=True)
    p.set_defaults(func=cmd_show)

    def arms_args(p):
        p.add_argument("--treat"); p.add_argument("--control")
        p.add_argument("--ri-draws", type=int, default=4999)

    p = sub.add_parser("analyze", help="ITT 效果估计与缺测敏感性")
    common(p); arms_args(p)
    p.add_argument("--out"); p.add_argument("--json")
    p.add_argument("--score-min", type=float, default=0.0)
    p.add_argument("--score-max", type=float, default=10.0)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("capacity", help="场次容量与席位压力")
    common(p); p.add_argument("--out"); p.add_argument("--json")
    p.set_defaults(func=cmd_capacity)

    p = sub.add_parser("review", help="扩场复核证据包与建议")
    common(p); arms_args(p)
    p.add_argument("--out"); p.add_argument("--json")
    p.add_argument("--school", required=True); p.add_argument("--plan")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("sign", help="签发决定（追加台账）")
    common(p); arms_args(p)
    p.add_argument("--school", required=True); p.add_argument("--plan")
    p.add_argument("--decision", choices=review.DECISIONS)
    p.add_argument("--reviewer", default=""); p.add_argument("--note", default="")
    p.add_argument("--log", default="decisions.jsonl")
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser("history", help="查看某校签发历史")
    p.add_argument("--school", required=True)
    p.add_argument("--log", default="decisions.jsonl")
    p.set_defaults(func=cmd_history)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
