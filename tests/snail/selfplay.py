#!/usr/bin/env python3
"""Engine-vs-engine smoke test for the snail variants: the engine must never crash, hang or play
an illegal move, including in lines where snails crush pieces and kings.

    python3 tests/snail/selfplay.py src/stockfish [--games 2] [--movetime 30]
"""
import argparse
import os
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pyffish as sf  # noqa: E402

VARIANTS = [f"snail-{n}-{m}-{s}" for n in (2, 3, 4) for m in "ds" for s in "uw"]


class Engine:
    def __init__(self, path):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.send("uci")
        self.wait("uciok")

    def send(self, cmd):
        self.p.stdin.write(cmd + "\n")

    def wait(self, prefix):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("engine exited")
            if line.startswith(prefix):
                return line.strip()

    def best(self, variant, moves, movetime):
        self.send(f"position startpos moves {' '.join(moves)}" if moves else "position startpos")
        self.send(f"go movetime {movetime}")
        return self.wait("bestmove").split()[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("engine")
    ap.add_argument("--games", type=int, default=2)
    ap.add_argument("--movetime", type=int, default=30)
    ap.add_argument("--max-plies", type=int, default=200)
    args = ap.parse_args()
    endings = Counter()
    for v in VARIANTS:
        eng = Engine(args.engine)
        eng.send(f"setoption name UCI_Variant value {v}")
        start = sf.start_fen(v)
        for g in range(args.games):
            eng.send("ucinewgame")
            moves = []
            # A different first move per game so the games differ
            first = sorted(sf.legal_moves(v, start, []))[g * 3 % 19]
            moves.append(first)
            while len(moves) < args.max_plies:
                end, _ = sf.is_immediate_game_end(v, start, moves)
                legal = sf.legal_moves(v, start, moves)
                if end or not legal or sf.is_optional_game_end(v, start, moves)[0]:
                    break
                m = eng.best(v, moves, args.movetime)
                if m not in legal:
                    print(f"ILLEGAL {v} game {g}: {m} after {' '.join(moves)}")
                    return 1
                moves.append(m)
            end, value = sf.is_immediate_game_end(v, start, moves)
            if end:
                kind = "snail/exposed-king end" if value else "both kings"
            elif not sf.legal_moves(v, start, moves):
                kind = "mate/stalemate"
            elif len(moves) >= args.max_plies:
                kind = "ply limit"
            else:
                kind = "repetition/50-move"
            endings[kind] += 1
            print(f"{v} game {g}: {len(moves)} plies, {kind}", flush=True)
        eng.send("quit")
    print(dict(endings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
