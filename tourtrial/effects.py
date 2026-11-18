"""按随机分配与校内比较口径估计邀请效果（ITT）。

- 估计量：学生层面 y ~ 处理指示 + 学校固定效应；对照口径为学校内部比较。
- 不确定性：班级聚类稳健标准误（CR1）+ 校内班级置换的随机化推断 p 值；
  同时给出把学生当独立个体的"朴素标准误"，仅用于对照说明其不可取。
- 小测缺测：未测学生不算答错；给出最好/最坏情形界与"临界点"敏感性范围，
  用以判断结论是否依赖对缺测者的乐观假设。
"""
from __future__ import annotations

import math

from . import stats
from .panel import Panel


def _cluster_key(stu: dict) -> str:
    return f"{stu['school']}||{stu['class_id']}"


def school_cells(panel: Panel, treat: str, control: str) -> dict:
    """每个学校 × 组别的班级数与学生数（分配证据的骨架）。"""
    cells: dict[str, dict] = {}
    for stu in panel.students:
        if stu["arm"] not in (treat, control):
            continue
        cell = cells.setdefault(stu["school"], {}).setdefault(
            stu["arm"], {"classes": set(), "students": 0})
        cell["classes"].add(stu["class_id"])
        cell["students"] += 1
    out = {}
    for school, arms in cells.items():
        out[school] = {arm: {"classes": len(v["classes"]), "students": v["students"]}
                       for arm, v in arms.items()}
    return out


def estimate_itt(panel: Panel, outcome, treat: str, control: str,
                 label: str = "", run_ri: bool = True,
                 ri_draws: int = 4999, seed: int = 20240601) -> dict:
    """单个结局的 ITT 估计。outcome(stu) -> float | None（None 视为缺测，不计入）。"""
    sample = [s for s in panel.students
              if s["arm"] in (treat, control) and outcome(s) is not None]
    n = len(sample)
    result: dict = {"label": label, "treat": treat, "control": control, "n": n}

    schools = sorted({s["school"] for s in sample})
    result["n_treat"] = sum(1 for s in sample if s["arm"] == treat)
    result["n_control"] = n - result["n_treat"]
    result["mean_treat"] = _mean([outcome(s) for s in sample if s["arm"] == treat])
    result["mean_control"] = _mean([outcome(s) for s in sample if s["arm"] == control])

    cells = school_cells(panel, treat, control)
    no_compare = [sc for sc, arms in cells.items()
                  if arms.get(treat, {}).get("classes", 0) == 0
                  or arms.get(control, {}).get("classes", 0) == 0]
    if no_compare:
        result.setdefault("warnings", []).append(
            f"以下学校缺少校内对照（某一组别没有班级），不进入校内比较: {', '.join(no_compare)}")

    if n == 0 or result["n_treat"] == 0 or result["n_control"] == 0:
        result["error"] = "可用样本为空或某一组别没有学生"
        return result

    school_idx = {sc: i for i, sc in enumerate(schools)}
    x_rows, y, clusters = [], [], []
    for s in sample:
        row = [1.0 if s["arm"] == treat else 0.0]
        row += [1.0 if school_idx[s["school"]] == j else 0.0 for j in range(len(schools))]
        x_rows.append(row)
        y.append(float(outcome(s)))
        clusters.append(_cluster_key(s))

    try:
        beta, inv, resid = stats.ols(x_rows, y)
    except stats.LinAlgError as exc:
        result["error"] = str(exc)
        return result

    est = beta[0]
    vcv_cluster, g = stats.cluster_vcov(x_rows, resid, inv, clusters)
    vcv_naive = stats.naive_vcov(resid, inv)
    se_cluster = math.sqrt(vcv_cluster[0][0]) if vcv_cluster[0][0] >= 0 else float("nan")
    se_naive = math.sqrt(vcv_naive[0][0]) if vcv_naive[0][0] >= 0 else float("nan")
    df = g - 1
    t_stat = est / se_cluster if se_cluster and not math.isnan(se_cluster) else float("nan")
    p_val = stats.t_pvalue_two_sided(t_stat, df)
    crit = stats.t_crit_975(df)

    result.update({
        "estimate": est, "se_cluster": se_cluster, "se_naive_independent": se_naive,
        "t": t_stat, "df": df, "p_value": p_val,
        "ci_low": est - crit * se_cluster if not math.isnan(crit) else float("nan"),
        "ci_high": est + crit * se_cluster if not math.isnan(crit) else float("nan"),
        "clusters": g, "schools": len(schools),
    })
    if g < 10:
        result.setdefault("warnings", []).append(
            f"班级数仅 {g} 个，聚类稳健标准误在极少班级下可能失真，请以随机化推断 p 值为准")

    if run_ri:
        result["randomization_inference"] = _ri(sample, outcome, treat, control,
                                                schools, ri_draws, seed)
    return result


def _ri(sample, outcome, treat, control, schools, draws, seed):
    """校内班级置换：统计量取精度加权的校内均值差之和。"""
    by_school: dict[str, dict[str, list]] = {}
    for s in sample:
        cls = by_school.setdefault(s["school"], {}).setdefault(_cluster_key(s), {
            "arm": s["arm"], "n": 0, "sum": 0.0})
        cls["n"] += 1
        cls["sum"] += float(outcome(s))

    school_names = [sc for sc in schools if sc in by_school]
    class_info = {sc: list(by_school[sc].values()) for sc in school_names}
    labels = [[c["arm"] for c in class_info[sc]] for sc in school_names]

    def stat_fn(assignment):
        total = 0.0
        for sc, assign in zip(school_names, assignment):
            sum_t = sum(c["sum"] for c, a in zip(class_info[sc], assign) if a == treat)
            n_t = sum(c["n"] for c, a in zip(class_info[sc], assign) if a == treat)
            sum_c = sum(c["sum"] for c, a in zip(class_info[sc], assign) if a == control)
            n_c = sum(c["n"] for c, a in zip(class_info[sc], assign) if a == control)
            if n_t and n_c:
                w = n_t * n_c / (n_t + n_c)
                total += w * (sum_t / n_t - sum_c / n_c)
        return total

    observed = stat_fn(labels)
    if all(len(set(lab)) < 2 for lab in labels):
        return {"p_value": float("nan"), "n_perms": 0, "exact": True,
                "note": "没有学校同时具备两组班级，无法做校内置换"}
    return stats.ri_pvalue(labels, stat_fn, observed, draws=draws, seed=seed)


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


# ---------- 常用结局 ----------

def outcome_participation(stu: dict):
    return 1.0 if stu["attended"] else 0.0


def outcome_quiz_endline(stu: dict):
    return stu["quiz_endline"]  # 未测 -> None -> 不计入，绝不算答错


def outcome_quiz_gain(stu: dict):
    if stu["quiz_endline"] is None or stu["quiz_baseline"] is None:
        return None
    return stu["quiz_endline"] - stu["quiz_baseline"]


def outcome_quiz_tested(stu: dict):
    return 1.0 if stu["quiz_endline_answered"] else 0.0


# ---------- 缺测敏感性 ----------

def quiz_missingness_sensitivity(panel: Panel, treat: str, control: str,
                                 score_min: float = 0.0, score_max: float = 10.0,
                                 step: float = 0.25) -> dict:
    """期末小测缺测的敏感性范围。

    - 最好/最坏情形界：缺测者分别按量表端点填补，给出效应估计的可行区间。
    - 临界点：假设处理组缺测者真实均分比同组已测者低（结论为负时则为高）delta 分，
      对照组缺测者等于已测均值；报告使结论不再显著 / 变号的最小 delta。
      对称地也报告对照组缺测者不利情形的临界点。
    """
    scoped = [s for s in panel.students if s["arm"] in (treat, control)]
    n_missing = sum(1 for s in scoped if not s["quiz_endline_answered"])
    primary = estimate_itt(panel, outcome_quiz_endline, treat, control,
                           label="期末小测（仅已测）", run_ri=False)
    out: dict = {"n_missing": n_missing, "n_scoped": len(scoped), "primary": primary}
    if "error" in primary:
        return out

    def imputed_outcome(treat_fill, control_fill):
        def fn(stu):
            if stu["quiz_endline"] is not None:
                return stu["quiz_endline"]
            return treat_fill if stu["arm"] == treat else control_fill
        return fn

    out["bound_low"] = estimate_itt(panel, imputed_outcome(score_min, score_max),
                                    treat, control, label="最坏情形（处理缺测=下限, 对照缺测=上限）",
                                    run_ri=False)
    out["bound_high"] = estimate_itt(panel, imputed_outcome(score_max, score_min),
                                     treat, control, label="最好情形（处理缺测=上限, 对照缺测=下限）",
                                     run_ri=False)

    mean_t = _mean([s["quiz_endline"] for s in scoped
                    if s["arm"] == treat and s["quiz_endline"] is not None])
    mean_c = _mean([s["quiz_endline"] for s in scoped
                    if s["arm"] == control and s["quiz_endline"] is not None])
    sign = 1.0 if primary["estimate"] >= 0 else -1.0

    def clip(x):
        return min(max(x, score_min), score_max)

    def tip(delta, adverse_arm):
        def fn(stu):
            if stu["quiz_endline"] is not None:
                return stu["quiz_endline"]
            if adverse_arm == "treat":
                return clip(mean_t - sign * delta) if stu["arm"] == treat else mean_c
            return mean_t if stu["arm"] == treat else clip(mean_c + sign * delta)
        return estimate_itt(panel, fn, treat, control, run_ri=False)

    out["tipping"] = {}
    span = score_max - score_min
    for adverse_arm, key in (("treat", "treat_missing_adverse"),
                             ("control", "control_missing_adverse")):
        lose_sig, flip = None, None
        delta = 0.0
        while delta <= span + 1e-9:
            res = tip(delta, adverse_arm)
            if "error" not in res:
                sig = (res["ci_low"] > 0) if sign > 0 else (res["ci_high"] < 0)
                if not sig and lose_sig is None:
                    lose_sig = delta
                if (sign > 0 and res["estimate"] <= 0) or (sign < 0 and res["estimate"] >= 0):
                    flip = delta
                    break
            delta += step
        out["tipping"][key] = {
            "delta_lose_significance": lose_sig if lose_sig is not None else f"> {span}",
            "delta_sign_flip": flip if flip is not None else f"> {span}",
        }
    return out
