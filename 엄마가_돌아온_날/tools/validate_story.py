#!/usr/bin/env python3
"""작품 정본의 구조·날짜·참조를 검사한다. Python 3.9 이상, 외부 의존성 없음.

실행 위치와 관계없이 이 스크립트의 상위 작품 폴더를 읽는다.
문장 의미·인물 동기·작품성까지 검증하는 도구는 아니다.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def ids(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{number:02d}" for number in range(1, count + 1)]


def age_on(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def main() -> int:
    canon = json.loads((ROOT / "data/canon.json").read_text(encoding="utf-8"))
    checks: list[tuple[bool, str]] = []

    def require(ok: bool, message: str) -> None:
        checks.append((bool(ok), message))

    def document(name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    expected = canon["expected_files"]
    require(len(expected) == 17 and len(set(expected)) == 17, "필수 파일 17개가 고유한가")
    for name in expected:
        path = ROOT / name
        require(path.is_file() and path.stat().st_size > 0, f"파일 존재·내용: {name}")

    clock = canon["clock"]
    original = datetime.fromisoformat(clock["original_at"])
    rewind = datetime.fromisoformat(clock["rewind_at"])
    deadline = datetime.fromisoformat(clock["return_deadline"])
    activation = datetime.fromisoformat(clock["activation_at"])
    require(original.tzinfo is not None and rewind.tzinfo is not None, "시각에 시간대가 명시됐는가")
    require(all(t.utcoffset() == timedelta(hours=9) for t in (original, rewind, deadline, activation)), "기준 시각은 한국 표준시인가")
    require(original.replace(year=original.year - 10) == rewind, "회귀 시작은 정확히 10년 전 같은 날짜·시각인가")
    require(clock["window_hours"] == 336, "창의 길이는 336시간인가")
    require(deadline - rewind == timedelta(hours=clock["window_hours"]), "기한과 시작의 차이가 336시간인가")
    require(rewind < activation < deadline, "작동이 회귀 이후이며 기한 전인가")
    require(deadline - activation == timedelta(seconds=10), "최종 작동은 기한보다 10초 앞서는가")
    require(clock["required_nodes"] == 12, "필수 거점은 12개인가")

    characters = canon["characters"]
    character_ids = [c["id"] for c in characters]
    require(character_ids == ids("C", 7), "인물 ID가 C01–C07로 고유·연속인가")
    living_original: list[str] = []
    absent_original: list[str] = []
    for c in characters:
        born = date.fromisoformat(c["born_on"])
        death = date.fromisoformat(c["died_on_original"]) if c["died_on_original"] else None
        require(death is None or born < death, f"{c['id']} 출생·사망 순서")
        alive_b = born <= rewind.date() and (death is None or death > rewind.date())
        alive_o = born <= original.date() and (death is None or death > original.date())
        mode = "future_memory" if alive_b and alive_o else "past_only" if alive_b else "absent"
        require(c["memory_mode"] == mode, f"{c['id']} 기억 자격")
        expected_b_age = age_on(born, rewind.date()) if alive_b else None
        expected_o_age = age_on(born, original.date()) if alive_o else None
        require(c["age_at_rewind"] == expected_b_age, f"{c['id']} 회귀 시점 만 나이")
        require(c["age_at_original"] == expected_o_age, f"{c['id']} 원래 시점 생존·나이")
        (living_original if alive_o else absent_original).append(c["id"])

    scenes = canon["scenes"]
    scene_ids = [s["id"] for s in scenes]
    require(scene_ids == ids("S", 48), "장면 ID가 S01–S48로 고유·연속인가")
    units = canon["units"]
    unit_ids = [u["id"] for u in units]
    require(unit_ids == ids("U", 12), "서사 단위가 U01–U12인가")
    require([sid for u in units for sid in u["scene_ids"]] == scene_ids, "단위별 장면 목록이 전체 48개를 순서대로 한 번씩 포함하는가")
    for u in units:
        require(len(u["scene_ids"]) == 4, f"{u['id']} 핵심 장면 4개")
        actual = [s["id"] for s in scenes if s["unit_id"] == u["id"]]
        require(actual == u["scene_ids"], f"{u['id']} 장면 소속 일치")
    previous_by_world: dict[str, datetime] = {}
    for s in scenes:
        at = datetime.fromisoformat(s["at"])
        world = s["world"]
        require(s["unit_id"] in unit_ids, f"{s['id']} 유효한 서사 단위")
        require(s["viewpoint"] in character_ids, f"{s['id']} 유효한 시점 인물")
        require(at.utcoffset() == timedelta(hours=9), f"{s['id']} 한국 표준시")
        require(world in {"B", "O"}, f"{s['id']} 유효한 세계 상태")
        valid_time = rewind <= at <= activation if world == "B" else at >= original
        require(valid_time, f"{s['id']} 세계 상태별 유효 시각")
        if world in previous_by_world:
            require(previous_by_world[world] <= at, f"{s['id']} 같은 상태 내 사건 순서")
        previous_by_world[world] = at
    require([s["world"] for s in scenes] == ["B"] * 44 + ["O"] * 4, "44개 B 장면 이후 4개 O 장면인가")
    require(scenes[43]["at"] == clock["activation_at"], "S44의 복귀 시각 일치")
    require(scenes[44]["at"] == clock["original_at"], "S45의 원래 시점 재개 일치")

    events = canon["events"]
    require([e["id"] for e in events] == ids("E", 24), "사건 ID가 E01–E24인가")
    require([sid for e in events for sid in e["scene_ids"]] == scene_ids, "사건이 전체 장면을 한 번씩 포함하는가")
    for e in events:
        require(len(e["scene_ids"]) == 2, f"{e['id']} 두 핵심 장면 대응")

    scene_doc = document("11_핵심장면_48개.md")
    require(re.findall(r"^### (S\d{2})\.", scene_doc, re.M) == scene_ids, "장면 문서와 데이터의 48개 장면 순서 일치")
    require(re.findall(r"^## (U\d{2})\.", scene_doc, re.M) == unit_ids, "장면 문서와 데이터의 12개 단위 일치")
    rule_ids = [r["id"] for r in canon["rules"]]
    require(rule_ids == ids("R", 14), "규칙 ID가 R01–R14인가")
    rule_doc = document("02_세계관과_시간규칙.md")
    require(re.findall(r"^### (R\d{2})\.", rule_doc, re.M) == rule_ids, "규칙 문서와 데이터 일치")
    event_doc = document("08_사건인과.md")
    require(re.findall(r"^\| (E\d{2}) \|", event_doc, re.M) == ids("E", 24), "인과표의 24개 사건 일치")
    info_doc = document("09_정보공개.md")
    require(canon["knowledge_ids"] == ids("K", 12), "정보 ID가 K01–K12인가")
    require(re.findall(r"^\| (K\d{2}) \|", info_doc, re.M) == canon["knowledge_ids"], "정보 공개표의 12개 항목 일치")
    foreshadow_doc = document("10_복선과_회수.md")
    require(canon["foreshadow_ids"] == ids("F", 12), "복선 ID가 F01–F12인가")
    require(re.findall(r"^\| (F\d{2}) \|", foreshadow_doc, re.M) == canon["foreshadow_ids"], "복선표의 12개 항목 일치")

    for name in expected:
        if not name.endswith(".md"):
            continue
        text = document(name)
        refs = set(re.findall(r"\bS\d{2}\b", text))
        require(refs <= set(scene_ids), f"{name}의 장면 ID 참조 범위")
        for target in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            local = (ROOT / name).parent / unquote(parsed.path)
            require(local.is_file(), f"{name}의 상대 링크: {target}")

    ending = canon["ending"]
    require(ending["return_succeeds"] is True, "정본 결말은 복귀 성립인가")
    require(ending["alive_in_original"] == living_original, "결말 생존 인물과 연표 일치")
    require(ending["absent_in_original"] == absent_original, "결말 부재 인물과 연표 일치")
    for key in ("physical_keepsakes_cross", "harin_has_B_memories", "new_visit_to_B_possible", "opponents_automatically_agree"):
        require(ending[key] is False, f"결말의 금지 예외가 꺼져 있는가: {key}")

    failures = [message for ok, message in checks if not ok]
    if failures:
        print(f"구조 검증 실패: {len(failures)}개 / 검사 {len(checks)}개")
        for message in failures:
            print(f"- {message}")
        return 1
    print(f"구조 검증 통과: {len(checks)}개 검사")
    print("파일 17개 / 인물 7명 / 규칙 14개 / 서사 단위 12개 / 핵심 장면 48개 / 사건 24개")
    print("정보 공개 12개 / 복선 12개 / 기억 자격·날짜·상대 링크 일치")
    print("주의: 문학적 완성도·대사의 자연스러움·모든 의미상 모순까지 보증하지 않습니다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"검증 실행 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
