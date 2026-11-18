"""签发决定的只增不改台账。

- 每次签发追加一条 JSON 记录（JSONL），旧记录永不改写；
- 补录小测或更正名额后可重新评估并再次签发，新记录以 supersedes 指向旧记录；
- 已发给学校的决定留在台账中，任何更正都是新记录，不是悄悄改掉。
"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


def code_version() -> str:
    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if git.returncode == 0:
            return f"tourtrial-{__version__}+git.{git.stdout.strip()}"
    except Exception:
        pass
    return f"tourtrial-{__version__}"


def make_record(school: str, decision: str, evidence: dict,
                reviewer: str, note: str, supersedes: str | None) -> dict:
    return {
        "record_id": uuid.uuid4().hex[:12],
        "school": school,
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "recommendation": evidence.get("recommendation"),
        "reasons": evidence.get("reasons", []),
        "warnings": evidence.get("warnings", []),
        "reviewer": reviewer,
        "note": note,
        "inputs_hash": evidence.get("inputs_hash"),
        "code_version": code_version(),
        "supersedes": supersedes,
        "evidence": evidence,  # 签发时采用的资料与判断一并留存
    }


def append_decision(log_path: str | Path, record: dict) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_decisions(log_path: str | Path) -> list[dict]:
    path = Path(log_path)
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path} 第{lineno}行不是合法 JSON，台账可能被人为改动: {exc}")
    return records


def history(log_path: str | Path, school: str) -> list[dict]:
    return [r for r in load_decisions(log_path) if r["school"] == school]


def latest(log_path: str | Path, school: str) -> dict | None:
    records = history(log_path, school)
    return records[-1] if records else None
