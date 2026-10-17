#!/usr/bin/env python3
"""Check the snail variants against the game's own rules engine.

The game (github.com/sirsigmund79/snail-chess) is the reference. Dump positions there with

    npx tsx scripts/dump-positions.ts --games 60 --out positions.jsonl

then, with pyffish built from this fork (python3 setup.py build_ext --inplace at the root):

    python3 tests/snail/compare.py positions.jsonl [--max-report 20]

For every position it compares the legal moves, the position after the move played (snails,
crushes, castling rights, clocks), and how the game stands afterwards. It exits non-zero on any
mismatch, so it can run in CI.
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pyffish as sf  # noqa: E402


def comparable(fen):
    """FEN without the en passant field: the game writes it after any double step, the engine
    only when a capture is possible. Legal moves still cover en passant captures."""
    parts = fen.split(" ")
    return " ".join(parts[:3] + parts[4:])


def engine_status(variant, fen, moves):
    """How the game stands after `moves` from `fen`, in the game's terms where we can tell."""
    end, value = sf.is_immediate_game_end(variant, fen, moves)
    after = sf.get_fen(variant, fen, moves)
    to_move = after.split(" ")[1]
    other = "b" if to_move == "w" else "w"
    if not end and not sf.legal_moves(variant, fen, moves):
        end, value = True, sf.game_result(variant, fen, moves)
    if not end:
        return {"result": "ongoing"}
    if value == 0:
        return {"result": "draw"}
    return {"result": "win", "winner": to_move if value > 0 else other}


def expected_status(status):
    result = status["result"]
    if result == "ongoing":
        return {"result": "ongoing"}
    if result == "draw":
        if status.get("reason") in ("threefold_repetition", "fifty_move_rule", "insufficient_material"):
            return None  # claimable draws: checked per game below
        return {"result": "draw"}
    return {"result": "win", "winner": status["winner"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("positions")
    ap.add_argument("--max-report", type=int, default=20)
    args = ap.parse_args()

    checked = Counter()
    problems = defaultdict(list)

    def report(kind, line, **detail):
        problems[kind].append({"variant": line["variant"], "game": line["game"], "ply": line["ply"],
                               "fen": line["fen"], "move": line["move"], **detail})

    with open(args.positions) as f:
        for raw in f:
            line = json.loads(raw)
            v, fen, move = line["variant"], line["fen"], line["move"]
            checked[v] += 1

            legal = sorted(sf.legal_moves(v, fen, []))
            if legal != line["legal"]:
                report("legal moves", line,
                       missing=sorted(set(line["legal"]) - set(legal)), extra=sorted(set(legal) - set(line["legal"])))
                continue

            after = sf.get_fen(v, fen, [move])
            if comparable(after) != comparable(line["after"]):
                report("position after move", line, expected=line["after"], engine=after)
                continue

            want = expected_status(line["status"])
            got = engine_status(v, fen, [move])
            if want is not None and got != want:
                # A draw the game ends at once (repetition etc.) is still ongoing for the engine.
                report("game status", line, expected=line["status"], engine=got)

            if "moves" in line and line["status"].get("reason") in ("threefold_repetition", "fifty_move_rule", "insufficient_material"):
                start = sf.start_fen(v)
                reason = line["status"]["reason"]
                if reason == "insufficient_material":
                    ok = all(sf.has_insufficient_material(v, start, line["moves"]))
                else:
                    ok = sf.is_optional_game_end(v, start, line["moves"])[0]
                if not ok:
                    report("claimable draw", line, expected=reason)

    total = sum(checked.values())
    print(f"checked {total} positions in {len(checked)} variants")
    for v in sorted(checked):
        print(f"  {v:12} {checked[v]}")
    if not problems:
        print("all match")
        return 0
    for kind, items in problems.items():
        print(f"\n{kind}: {len(items)} mismatches")
        for item in items[: args.max_report]:
            print("  " + json.dumps(item))
    return 1


if __name__ == "__main__":
    sys.exit(main())
