"""Fair dice for online games, and checking them afterwards.

Whoever runs the server rolls the dice for every measurement. If one of the players is also
the host, they could choose the outcomes. To prevent that, both sides contribute to the seed:

1. On creating the game, the server picks a secret and publishes only its SHA-256
   (the *commitment*).
2. The joining player sends a random seed of their own, after seeing the commitment.
3. Measurement *n* uses ``sha256(secret ‖ guest_seed ‖ n)``, so neither side alone can
   choose any outcome: the server committed before seeing the guest's seed, and the guest
   doesn't know the secret.
4. When the game ends, the server reveals the secret. Anyone can check it against the
   commitment and replay the game with the same dice: every recorded outcome must match.

A host running modified code could still *look ahead* at upcoming outcomes during the game,
since the server must know the seed to roll the dice. Only a neutral server rules that out.

The joining player must keep their own copy of their seed: checking against the copy in the
game record alone would let a server swap in a seed that fits outcomes it chose. The UI keeps
it and shows it. Verify a finished game from the command line::

    python -m api.fairness http://192.168.1.20:52814/?game=0123456789ab --seed <your seed>
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from engine.board import IllegalMoveError, QuantumBoard


def new_secret() -> str:
    return secrets.token_hex(32)


def commitment(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class SeededDice:
    """Counter-based dice: the n-th roll is ``sha256(secret ‖ guest_seed ‖ n)`` as a number in
    [0, 1). Trivial to reimplement anywhere, unlike a library generator's internal stream."""

    def __init__(self, secret: str, guest_seed: str) -> None:
        self._key = f"{secret}:{guest_seed}:".encode()
        self.rolls = 0

    def random(self) -> float:
        digest = hashlib.sha256(self._key + str(self.rolls).encode()).digest()
        self.rolls += 1
        return int.from_bytes(digest[:8], "big") / 2**64


@dataclass(frozen=True)
class Verdict:
    fair: bool
    reason: str


def verify(state: dict, my_seed: Optional[str] = None) -> Verdict:
    """Check a finished online game (a ``GameState`` as JSON) against its revealed secret.

    ``my_seed`` is the seed the joining player sent. Pass it whenever you have it: otherwise a
    server could swap in a seed of its own that fits outcomes it chose.
    """
    fairness: Optional[dict] = state.get("fairness")
    if not fairness:
        return Verdict(False, "This is not an online game, so there is nothing to verify.")
    secret, guest_seed = fairness.get("secret"), fairness.get("guest_seed")
    if guest_seed is None:
        return Verdict(False, "Nobody has joined this game yet.")
    if secret is None:
        return Verdict(
            False, "The game is still running. The server reveals its secret at the end."
        )
    if commitment(secret) != fairness.get("commitment"):
        return Verdict(
            False, "The revealed secret does not match the commitment made at the start."
        )
    if my_seed is not None and my_seed != guest_seed:
        return Verdict(False, "The server used a different seed from the one you sent.")

    dice = SeededDice(secret, guest_seed)
    board = QuantumBoard(state["initial_fen"], rng=dice)
    for ply, entry in enumerate(state["history"], start=1):
        try:
            result = board.do_move(entry["notation"])
        except (IllegalMoveError, ValueError) as exc:
            return Verdict(False, f"Move {ply} ({entry['notation']}) does not replay: {exc}")
        if result.outcomes != entry["outcomes"] or result.executed != entry["executed"]:
            return Verdict(
                False,
                f"Move {ply} ({entry['notation']}): the dice say {result.outcomes}, "
                f"but the game recorded {entry['outcomes']}.",
            )
    rolls = dice.rolls
    if my_seed is None:
        return Verdict(
            True,
            f"All {rolls} measurement outcomes match the recorded seeds. Without the joining "
            "player's own copy of their seed, this can't rule out a swapped seed.",
        )
    return Verdict(True, f"All {rolls} measurement outcomes match the dice both players seeded.")


def main(argv: Optional[list[str]] = None) -> None:
    import httpx

    parser = argparse.ArgumentParser(description="Check that a finished online game was fair.")
    parser.add_argument("link", help="the game's link, e.g. http://host:8000/?game=<id>")
    parser.add_argument("--seed", help="the seed you sent when joining (shown in the game)")
    args = parser.parse_args(argv)
    parts = urlsplit(args.link)
    game_id = (parse_qs(parts.query).get("game") or parse_qs(parts.query).get("join") or [None])[0]
    if not game_id:
        sys.exit("The link has no ?game=<id>.")
    state = httpx.get(
        f"{parts.scheme}://{parts.netloc}/state", params={"game_id": game_id}, timeout=10
    )
    state.raise_for_status()
    verdict = verify(state.json(), args.seed)
    print(("FAIR: " if verdict.fair else "NOT VERIFIED: ") + verdict.reason)
    sys.exit(0 if verdict.fair else 1)


if __name__ == "__main__":
    main()
