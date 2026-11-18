"""最小统计推断工具（仅标准库）。

- OLS（含学校固定效应）
- 班级聚类稳健标准误（CR1 有限样本修正）：学生不是独立随机，班级才是分配单位
- t 分布双侧 p 值（经由正则化不完全贝塔函数）
- 校内班级层面的随机化推断（精确枚举或蒙特卡洛）
"""
from __future__ import annotations

import itertools
import math
import random


class LinAlgError(Exception):
    pass


# ---------- 线性代数 ----------

def mat_inverse(a: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan 求逆（部分主元）。"""
    n = len(a)
    aug = [list(map(float, row)) + [1.0 if i == j else 0.0 for j in range(n)]
           for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[piv][col]) < 1e-12:
            raise LinAlgError("设计矩阵奇异：可能某个学校或某个组别内没有学生")
        aug[col], aug[piv] = aug[piv], aug[col]
        pv = aug[col][col]
        aug[col] = [v / pv for v in aug[col]]
        for r in range(n):
            if r != col:
                f = aug[r][col]
                if f:
                    aug[r] = [v - f * w for v, w in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def ols(x_rows: list[list[float]], y: list[float]):
    """返回 (beta, (X'X)^-1, resid)。"""
    k = len(x_rows[0])
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for row, yi in zip(x_rows, y):
        for a in range(k):
            ra = row[a]
            if ra == 0.0:
                continue
            xty[a] += ra * yi
            for b in range(k):
                if row[b]:
                    xtx[a][b] += ra * row[b]
    inv = mat_inverse(xtx)
    beta = [sum(inv[i][j] * xty[j] for j in range(k)) for i in range(k)]
    resid = [yi - sum(b * x for b, x in zip(beta, row)) for row, yi in zip(x_rows, y)]
    return beta, inv, resid


def cluster_vcov(x_rows: list[list[float]], resid: list[float],
                 inv: list[list[float]], clusters: list[str]):
    """CR1 聚类稳健方差协方差；返回 (V, 聚类数 G)。"""
    k = len(inv)
    scores: dict[str, list[float]] = {}
    for row, u, g in zip(x_rows, resid, clusters):
        s = scores.setdefault(g, [0.0] * k)
        for a in range(k):
            if row[a]:
                s[a] += row[a] * u
    meat = [[0.0] * k for _ in range(k)]
    for s in scores.values():
        for a in range(k):
            if s[a]:
                for b in range(k):
                    meat[a][b] += s[a] * s[b]
    tmp = [[sum(inv[i][m] * meat[m][j] for m in range(k)) for j in range(k)]
           for i in range(k)]
    vcv = [[sum(tmp[i][m] * inv[m][j] for m in range(k)) for j in range(k)]
           for i in range(k)]
    g = len(scores)
    n = len(resid)
    if g > 1 and n > k:
        c = (g / (g - 1)) * ((n - 1) / (n - k))
    else:
        c = float("nan")
    return [[c * v for v in row] for row in vcv], g


def naive_vcov(resid: list[float], inv: list[list[float]]):
    """经典（独立同分布）标准误。本试验中它把学生当作独立随机，仅供对照，不可取。"""
    n = len(resid)
    k = len(inv)
    if n <= k:
        return [[float("nan")] * k for _ in range(k)]
    sigma2 = sum(u * u for u in resid) / (n - k)
    return [[sigma2 * v for v in row] for row in inv]


# ---------- t 分布 ----------

def _betacf(a: float, b: float, x: float) -> float:
    max_it, eps, fpmin = 200, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_it + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_inc(a: float, b: float, x: float) -> float:
    """正则化不完全贝塔函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_pvalue_two_sided(t: float, df: float) -> float:
    """t 分布双侧 p 值；df<=0 时返回 nan。"""
    if df <= 0 or math.isnan(t):
        return float("nan")
    x = df / (df + t * t)
    return beta_inc(df / 2.0, 0.5, x)


def t_crit_975(df: float) -> float:
    """t 分布 0.975 分位（二分求逆）。"""
    if df <= 0 or math.isnan(df):
        return float("nan")
    lo, hi = 0.0, 1.0
    while t_pvalue_two_sided(hi, df) > 0.05:
        hi *= 2
        if hi > 1e6:
            return float("nan")
    for _ in range(80):
        mid = (lo + hi) / 2
        if t_pvalue_two_sided(mid, df) > 0.05:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------- 随机化推断 ----------

def school_permutations(labels: list) -> list[tuple]:
    """一个学校内班级组别标签的全部不同排列。"""
    seen: set[tuple] = set()
    out = []
    for p in itertools.permutations(labels):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def ri_pvalue(school_class_labels: list[list],
              stat_fn, observed: float,
              exact_limit: int = 20000, draws: int = 4999,
              seed: int = 20240601):
    """校内班级层面置换的随机化推断（双侧）。

    school_class_labels: 每个学校一个列表，元素为该班组别标签。
    stat_fn(assignment) -> float，assignment 与输入同结构（置换后的标签）。
    返回 dict(p_value, n_perms, exact)。
    """
    per_school = [school_permutations(labels) for labels in school_class_labels]
    total = 1
    for perms in per_school:
        total *= len(perms)

    abs_obs = abs(observed)
    tol = 1e-12

    if total <= exact_limit:
        count = 0
        ge = 0
        for combo in itertools.product(*per_school):
            val = stat_fn(list(combo))
            count += 1
            if abs(val) >= abs_obs - tol:
                ge += 1
        return {"p_value": ge / count, "n_perms": count, "exact": True}

    rng = random.Random(seed)
    ge = 1  # 观测值本身计入
    for _ in range(draws):
        assignment = []
        for labels in school_class_labels:
            perm = list(labels)
            rng.shuffle(perm)
            assignment.append(perm)
        if abs(stat_fn(assignment)) >= abs_obs - tol:
            ge += 1
    return {"p_value": ge / (draws + 1), "n_perms": draws + 1, "exact": False}
