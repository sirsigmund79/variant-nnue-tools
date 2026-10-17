#!/usr/bin/env python3
"""Play two engine setups against each other in a snail variant and estimate the Elo difference.

Typical use, a new network against the last one:

    python3 tests/snail/match.py --variant snail-3-d-u --games 400 --movetime 50 \\
        --a src/stockfish --a-opt EvalFile=new.nnue \\
        --b src/stockfish --b-opt EvalFile=old.nnue

Each opening (a few random moves, seeded) is played twice with colours swapped, so neither
side gets the luckier openings. Games are judged with pyffish built from this fork, so they end
exactly where the game would end them (snail wins, both kings crushed, mates, dead positions,
repetition, 50-move rule). Prints wins/draws/losses for A and the Elo difference with a 95%
confidence interval. A positive Elo means A is stronger.
"""
import argparse
import math
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pyffish as sf  # noqa: E402


class Engine:
    def __init__(self, path, variant, options):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.send("uci")
        self.wait("uciok")
        self.send(f"setoption name UCI_Variant value {variant}")
        for opt in options:
            name, _, value = opt.partition("=")
            self.send(f"setoption name {name} value {value}")
        self.send("isready")
        self.wait("readyok")

    def send(self, cmd):
        self.p.stdin.write(cmd + "\n")

    def wait(self, prefix):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("engine exited")
            if line.startswith(prefix):
                return line.strip()

    def best(self, moves, movetime):
        self.send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
        self.send(f"go movetime {movetime}")
        return self.wait("bestmove").split()[1]

    def close(self):
        self.send("quit")
        self.p.wait(timeout=10)


def result(variant, start, moves):
    """Score for White (1, 0.5, 0) if the game is over, else None."""
    end, value = sf.is_immediate_game_end(variant, start, moves)
    if not end and not sf.legal_moves(variant, start, moves):
        end, value = True, sf.game_result(variant, start, moves)
    if not end:
        end, value = sf.is_optional_game_end(variant, start, moves)
    if not end:
        return None
    white_to_move = len(moves) % 2 == 0
    if value == 0:
        return 0.5
    side_to_move_wins = value > 0
    return 1.0 if side_to_move_wins == white_to_move else 0.0


def elo(score, games, scores):
    """Elo difference and half-width of a 95% interval from per-game scores."""
    if score <= 0 or score >= 1:
        return (math.inf if score >= 1 else -math.inf), math.nan
    mean = score
    var = sum((s - mean) ** 2 for s in scores) / max(games - 1, 1)
    margin = 1.96 * math.sqrt(var / games)
    to_elo = lambda p: -400 * math.log10(1 / min(max(p, 1e-6), 1 - 1e-6) - 1)
    return to_elo(mean), (to_elo(mean + margin) - to_elo(mean - margin)) / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="snail-3-d-u")
    ap.add_argument("--games", type=int, default=100, help="total games (rounded up to an even number)")
    ap.add_argument("--movetime", type=int, default=50, help="milliseconds per move")
    ap.add_argument("--opening-plies", type=int, default=4)
    ap.add_argument("--max-plies", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--a", required=True, help="engine binary A")
    ap.add_argument("--b", required=True, help="engine binary B")
    ap.add_argument("--a-opt", action="append", default=[], help="UCI option for A, NAME=VALUE (repeatable)")
    ap.add_argument("--b-opt", action="append", default=[], help="UCI option for B, NAME=VALUE (repeatable)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    v = args.variant
    start = sf.start_fen(v)
    a = Engine(args.a, v, args.a_opt)
    b = Engine(args.b, v, args.b_opt)
    wins = draws = losses = 0
    scores = []
    pairs = (args.games + 1) // 2
    for pair in range(pairs):
        opening = []
        for _ in range(args.opening_plies):
            legal = sf.legal_moves(v, start, opening)
            if not legal or sf.is_immediate_game_end(v, start, opening)[0]:
                break
            opening.append(rng.choice(sorted(legal)))
        for a_is_white in (True, False):
            moves = list(opening)
            for e in (a, b):
                e.send("ucinewgame")
            while (r := result(v, start, moves)) is None and len(moves) < args.max_plies:
                white_to_move = len(moves) % 2 == 0
                engine = a if white_to_move == a_is_white else b
                m = engine.best(moves, args.movetime)
                if m not in sf.legal_moves(v, start, moves):
                    print(f"illegal move {m} from {'A' if engine is a else 'B'} after {' '.join(moves)}")
                    return 1
                moves.append(m)
            white_score = 0.5 if r is None else r
            s = white_score if a_is_white else 1 - white_score
            scores.append(s)
            wins += s == 1
            draws += s == 0.5
            losses += s == 0
        n = len(scores)
        e, margin = elo(sum(scores) / n, n, scores)
        estimate = f"Elo {e:+.0f} ± {margin:.0f}" if math.isfinite(e) else f"{'A' if e > 0 else 'B'} won every game"
        print(f"{n:4} games  A +{wins} ={draws} -{losses}  {estimate}", flush=True)
    a.close()
    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
