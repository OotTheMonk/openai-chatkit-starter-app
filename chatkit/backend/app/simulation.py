"""Local, seeded SWUSim opening and full-game simulations for a working draft."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
ENGINE_ROOT = Path(os.getenv("TCGENGINE_ROOT", str(ROOT.parent / "TCGEngine")))
RUNNER = ROOT / "simulation" / "turn_one_residual.php"
CARD_ID = re.compile(r"^[A-Z0-9]{2,5}_(?:T[0-9]{2}|[0-9]{2,3})$")
FIXTURE_NAME = re.compile(r"^[a-z0-9_]+$")
FIXTURE_DIRS = ("meta-2026-09", "meta-2026-09-field")


def _card_id(row: dict[str, Any] | None) -> str:
    value = str((row or {}).get("id") or (row or {}).get("cardID") or "")
    if CARD_ID.fullmatch(value):
        return value
    # SWUStats deck rows use numeric FFG IDs. The catalog enrichment already
    # attached the corresponding SWU-DB set/number printings to each row.
    for printing in (row or {}).get("printings") or []:
        if not isinstance(printing, dict):
            continue
        set_code = str(printing.get("set") or "").upper()
        number = str(printing.get("number") or "")
        if not re.fullmatch(r"[A-Z0-9]{2,5}", set_code):
            continue
        if re.fullmatch(r"T[0-9]{2}", number):
            suffix = number
        elif number.isdecimal() and 0 < int(number) < 1000:
            suffix = str(int(number)).zfill(2 if set_code == "TS26" else 3)
        else:
            continue
        candidate = f"{set_code}_{suffix}"
        if CARD_ID.fullmatch(candidate):
            return candidate
    raise ValueError(f"The deck contains a card without a usable SWUSim printing: {value or '(missing)'}.")


def deck_to_fixture(contents: dict[str, Any]) -> str:
    """Serialize the working main deck in SWUSim's text fixture format."""
    leader = _card_id(contents.get("leader"))
    base = _card_id(contents.get("base"))
    rows = contents.get("deck")
    if not isinstance(rows, list) or not rows:
        raise ValueError("The working deck has no main-deck cards.")
    cards: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("The working deck contains an invalid card row.")
        card = _card_id(row)
        count = row.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > 99:
            raise ValueError(f"Invalid count for {card}.")
        cards[card] = cards.get(card, 0) + count
    minimum = 60 if base == "JTL_024" else 45 if base == "JTL_025" else 50
    if sum(cards.values()) < minimum:
        raise ValueError(f"The working main deck needs at least {minimum} cards for this base.")
    return "\n".join(["Leader", f"1 {leader}", "", "Base", f"1 {base}", "", "Deck", *(
        f"{count} {card}" for card, count in sorted(cards.items())
    ), ""])


def _fixture_path(name: str) -> Path:
    if not FIXTURE_NAME.fullmatch(name):
        raise ValueError("Choose an available meta fixture.")
    for directory in FIXTURE_DIRS:
        path = ENGINE_ROOT / "SWUSim" / "Tests" / "BotFixtures" / directory / f"{name}.txt"
        if path.is_file():
            return path
    raise ValueError(f"Unknown meta fixture: {name}.")


def _check_engine_card_data(fixture: Path, deck_text: str) -> None:
    """Reject cards absent from SWUSim's generated source before starting games."""
    cache = ENGINE_ROOT / "SWUSim" / "GeneratedCode" / "cardArrayCache.json"
    if not cache.is_file():
        return  # The PHP runner still validates the loaded card dictionary.
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        known = {card.get("id") for card in data.get("cardArray", [])}
    except (OSError, ValueError):
        return
    card_lines = re.compile(r"^\s*\d+\s+([A-Z0-9]{2,5}_(?:T\d{2}|\d{2,3}))\s*$", re.MULTILINE)
    required = set(card_lines.findall(deck_text)) | set(card_lines.findall(fixture.read_text(encoding="utf-8")))
    missing = sorted(required - known)
    if missing:
        preview = ", ".join(missing[:8]) + (f" and {len(missing) - 8} more" if len(missing) > 8 else "")
        raise RuntimeError(f"Local SWUSim generated card data is missing {preview}. "
                           "Regenerate TCGEngine SWUSim card dictionaries from a complete card database before simulating.")


def available_opponents(cards: dict[str, dict[str, Any]] | None = None) -> list[dict[str, str | None]]:
    printing_ids = {}
    for card_id, card in (cards or {}).items():
        for printing in card.get("printings", []):
            if not isinstance(printing, dict):
                continue
            set_code = str(printing.get("set") or "").upper()
            number = str(printing.get("number") or "")
            if not set_code or not number:
                continue
            suffix = str(int(number)).zfill(2 if set_code == "TS26" else 3) if number.isdecimal() else number
            printing_ids[f"{set_code}_{suffix}"] = str(card_id)
    fixtures = []
    for directory in FIXTURE_DIRS:
        path = ENGINE_ROOT / "SWUSim" / "Tests" / "BotFixtures" / directory
        for file in sorted(path.glob("*.txt")):
            with file.open(encoding="utf-8") as source:
                lines = source.readlines()
            first_line = lines[0].strip().lstrip("# ") if lines else ""
            sections: dict[str, str] = {}
            section = ""
            for line in lines:
                line = line.strip()
                if line in ("Leader", "Base", "Deck"):
                    section = line
                elif section in ("Leader", "Base") and section not in sections and not line.startswith("#"):
                    match = re.fullmatch(r"1\s+([A-Z0-9]{2,5}_(?:T[0-9]{2}|[0-9]{2,3}))", line)
                    if match:
                        sections[section] = match.group(1)
            fixtures.append({"id": file.stem, "label": first_line or file.stem, "group": directory,
                             "leaderId": printing_ids.get(sections.get("Leader", "")),
                             "baseId": printing_ids.get(sections.get("Base", ""))})
    return fixtures


def _git_revision(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={path.as_posix()}", "rev-parse", "HEAD"],
        cwd=path, capture_output=True, text=True, timeout=5, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"ahead": 0, "equal": 0, "behind": 0, "no_unit_attack": 0, "failed": 0}
    differences = []
    unit_health_differences = []
    base_health = {"ours": [], "opponent": []}
    for sample in samples:
        if sample["status"] not in ("resolved_attack", "no_unit_attack"):
            counts["failed"] += 1
            continue
        if sample["status"] == "no_unit_attack":
            counts["no_unit_attack"] += 1
        units = sample["summary"]["unitCount"]
        ours = sum(units["2"].values())
        theirs = sum(units["1"].values())
        delta = ours - theirs
        differences.append(delta)
        health = sample["summary"]["remainingUnitHealth"]
        unit_health_differences.append(sum(health["2"].values()) - sum(health["1"].values()))
        bases = sample["afterAttack"]["baseHealth"]
        base_health["ours"].append(bases["2"])
        base_health["opponent"].append(bases["1"])
        counts["ahead" if delta > 0 else "behind" if delta < 0 else "equal"] += 1
    return {
        "counts": counts,
        "meanUnitDifference": sum(differences) / len(differences) if differences else None,
        "meanRemainingUnitHealthDifference": sum(unit_health_differences) / len(unit_health_differences) if unit_health_differences else None,
        "meanBaseHealth": {side: sum(values) / len(values) if values else None for side, values in base_health.items()},
        "scoredSamples": len(differences),
    }


def _aggregate_full_games(samples: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"ours": 0, "opponent": 0, "incomplete": 0}
    rounds = []
    actions = []
    our_health_in_wins = []
    opponent_health_in_losses = []
    for sample in samples:
        if sample.get("status") != "completed" or sample.get("winner") not in (1, 2):
            counts["incomplete"] += 1
            continue
        counts["ours" if sample["winner"] == 2 else "opponent"] += 1
        rounds.append(sample["rounds"])
        actions.append(sample["appliedSteps"])
        health = sample["afterAttack"]["baseHealth"]
        if sample["winner"] == 2:
            our_health_in_wins.append(health["2"])
        else:
            opponent_health_in_losses.append(health["1"])
    completed = counts["ours"] + counts["opponent"]
    return {"counts": counts, "completedGames": completed,
            "ourWinRate": counts["ours"] / completed if completed else None,
            "meanRounds": sum(rounds) / completed if completed else None,
            "meanActions": sum(actions) / completed if completed else None,
            "meanOurBaseHealthInWins": sum(our_health_in_wins) / len(our_health_in_wins) if our_health_in_wins else None,
            "meanOpponentBaseHealthInLosses": sum(opponent_health_in_losses) / len(opponent_health_in_losses) if opponent_health_in_losses else None}


def run_local(contents: dict[str, Any], deck_id: int, revision: int, opponent: str, seed: str, samples: int,
              mode: str = "residual") -> dict[str, Any]:
    started = time.perf_counter()
    if mode not in ("residual", "full_game"):
        raise ValueError("Choose a supported simulation mode.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", seed):
        raise ValueError("Use a seed of 1–64 letters, digits, underscores, or hyphens.")
    if not isinstance(samples, int) or isinstance(samples, bool) or not 1 <= samples <= 12:
        raise ValueError("Choose between 1 and 12 samples.")
    if not RUNNER.is_file() or not ENGINE_ROOT.is_dir():
        raise RuntimeError("The local SWUSim runner is unavailable.")
    php = os.getenv("SWUSIM_PHP_BIN") or shutil.which("php")
    if not php:
        raise RuntimeError("PHP is unavailable on the app host.")
    fixture = _fixture_path(opponent)
    deck_text = deck_to_fixture(contents)
    _check_engine_card_data(fixture, deck_text)
    deck_hash = hashlib.sha256(deck_text.encode("utf-8")).hexdigest()
    results = []
    timeout = 120 if mode == "full_game" else 45
    memory_only = mode == "full_game"
    workers = min(4, samples)
    with tempfile.TemporaryDirectory(prefix="swu-simulation-") as temporary:
        deck_path = Path(temporary) / "working-deck.txt"
        deck_path.write_text(deck_text, encoding="utf-8")
        def run_one(index: int) -> dict[str, Any]:
            sample_seed = f"{seed}-{index + 1:02d}"
            try:
                run = subprocess.run(
                    [str(php), "-d", "apc.enable_cli=1", "-d", "xdebug.mode=off", str(RUNNER),
                     f"--deck={fixture}", f"--deck2={deck_path}",
                     f"--seed={sample_seed}", f"--mode={mode}", *(["--memory-only"] if memory_only else [])],
                    cwd=ENGINE_ROOT, env={**os.environ, "TCGENGINE_ROOT": str(ENGINE_ROOT)},
                    capture_output=True, text=True, timeout=timeout, check=False,
                )
            except subprocess.TimeoutExpired:
                return {"status": "timeout", "seed": sample_seed, "engineError": f"SWUSim timed out after {timeout} seconds."}
            try:
                sample = json.loads(run.stdout)
            except json.JSONDecodeError:
                return {"status": "engine_error", "seed": sample_seed,
                        "engineError": f"SWUSim returned no JSON result: {run.stderr[-400:]}"}
            return sample
        # SWUSim allocates game IDs under a file lock. Each PHP process has its
        # own APCu state and mirrors the self-play harness's isolated workers.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_one, range(samples)))
    return {
        "schema": "swu-simulation-batch-v1", "mode": mode, "memoryOnly": memory_only,
        "workers": workers, "deckId": deck_id, "revision": revision,
        "deckHash": deck_hash, "opponent": opponent, "opponentFixture": str(fixture),
        "engineRevision": _git_revision(ENGINE_ROOT),
        "policy": "heuristic-normal" if mode == "full_game" else "residual-opening-v1",
        "seed": seed, "requestedSamples": samples, "samples": results,
        "aggregate": _aggregate_full_games(results) if mode == "full_game" else _aggregate(results),
        "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
    }
