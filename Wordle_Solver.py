#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interactive Wordle helper.

Loop:
  1) Enter guess (e.g., crane). Type 'q' to quit.
  2) Enter greens pattern with '.' for unknowns (e.g., '.r..e').
  3) Enter yellows as 'letter@pos' 1-based, space-separated (e.g., 'a@3 n@5').
The tool infers greys from letters in the guess not marked green or yellow.

Dictionary: one word per line. Case-insensitive. Defaults to 5-letter words inferred from first guess.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple


def load_words(path: Path, ignore_case: bool = True) -> List[str]:
    ws = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [w.lower() for w in ws] if ignore_case else ws


def filter_by_length(words: Iterable[str], length: int) -> List[str]:
    return [w for w in words if len(w) == length]


def parse_greens_pattern(pattern: str) -> Dict[int, str]:
    """Pattern like '.r..e' -> {1:'r', 4:'e'} with 0-based indices."""
    out: Dict[int, str] = {}
    for i, ch in enumerate(pattern.strip()):
        if ch != '.' and ch != '_':
            if not ch.isalpha() or len(ch) != 1:
                raise ValueError("Greens pattern must contain letters or '.' only.")
            out[i] = ch.lower()
    return out


def parse_yellows(spec: str, word_len: int) -> List[Tuple[str, int]]:
    """
    Parse 'a@3 n@5' into [('a',2), ('n',4)] 0-based.
    Accepts commas or spaces as separators. Positions are 1-based.
    """
    spec = spec.strip()
    if not spec:
        return []
    parts = [p for chunk in spec.replace(",", " ").split() for p in [chunk] if p]
    out: List[Tuple[str, int]] = []
    for p in parts:
        if "@" not in p:
            raise ValueError(f"Yellow entry '{p}' must be like letter@pos (1-based).")
        letter, pos = p.split("@", 1)
        if len(letter) != 1 or not letter.isalpha():
            raise ValueError(f"Bad yellow letter '{letter}'.")
        try:
            idx1 = int(pos)
        except ValueError:
            raise ValueError(f"Bad yellow position '{pos}'.")
        if not (1 <= idx1 <= word_len):
            raise ValueError(f"Yellow position {idx1} out of range 1..{word_len}.")
        out.append((letter.lower(), idx1 - 1))
    return out


def update_constraints_from_feedback(
    guess: str,
    greens: Dict[int, str],
    yellows: List[Tuple[str, int]],
    required_min_counts: Dict[str, int],
    banned_positions: Dict[str, Set[int]],
    excluded_letters: Set[str],
) -> None:
    """
    - required_min_counts[letter] = max(existing, #greens+yellows for that letter in this guess)
    - banned_positions[letter] includes all yellow indices for that letter
    - excluded_letters gets letters from guess not present as green or yellow at all in this guess
    """
    guess = guess.lower()
    # Count green+yellow per letter for this guess
    gy_marks = [greens.get(i, None) for i in range(len(guess))]
    gy_count: Counter[str] = Counter()

    for i, ch in enumerate(guess):
        # mark greens
        if i in greens and greens[i].lower() == ch:
            gy_count[ch] += 1

    # mark yellows
    for letter, idx in yellows:
        if 0 <= idx < len(guess) and guess[idx].lower() == letter:
            gy_count[letter] += 1
        banned_positions[letter].add(idx)

    # update min counts
    for letter, cnt in gy_count.items():
        if cnt > required_min_counts.get(letter, 0):
            required_min_counts[letter] = cnt

    # exclude pure greys from this guess
    greys = {ch for ch in set(guess) if gy_count.get(ch, 0) == 0}
    excluded_letters.update(greys)


def candidate_ok(
    word: str,
    greens: Dict[int, str],
    required_min_counts: Dict[str, int],
    banned_positions: Dict[str, Set[int]],
    excluded_letters: Set[str],
) -> bool:
    w = word.lower()
    # greens
    for i, ch in greens.items():
        if w[i] != ch:
            return False
    # excluded letters
    if any(ch in w for ch in excluded_letters):
        return False
    # yellow logic: must contain each yellowed letter and not at banned indices
    for letter, idxs in banned_positions.items():
        if letter not in w:
            return False
        for i in idxs:
            if w[i] == letter:
                return False
    # minimum counts
    wc = Counter(w)
    for letter, need in required_min_counts.items():
        if wc.get(letter, 0) < need:
            return False
    return True


def filter_candidates(
    words: Iterable[str],
    greens: Dict[int, str],
    required_min_counts: Dict[str, int],
    banned_positions: Dict[str, Set[int]],
    excluded_letters: Set[str],
) -> List[str]:
    return [
        w for w in words
        if candidate_ok(w, greens, required_min_counts, banned_positions, excluded_letters)
    ]


def score_by_letter_coverage(words: List[str]) -> List[Tuple[str, float]]:
    """
    Simple heuristic: score by sum of inverse frequency of unique letters.
    Promotes words that cover rarer letters to gain information.
    """
    if not words:
        return []
    freq: Counter[str] = Counter(ch for w in words for ch in set(w))
    inv = {ch: 1.0 / c for ch, c in freq.items()}
    scored = []
    for w in words:
        s = sum(inv.get(ch, 0.0) for ch in set(w))
        scored.append((w, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def interactive_loop(dictionary: List[str]) -> None:
    current_words = dictionary[:]  # start with all words of target length
    required_min_counts: Dict[str, int] = {}
    banned_positions: Dict[str, Set[int]] = defaultdict(set)
    excluded_letters: Set[str] = set()
    greens: Dict[int, str] = {}

    word_len = None

    while True:
        guess = input("\nGuess (or 'q' to quit): ").strip()
        if guess.lower() in {"q", "quit", "exit"}:
            break
        if not guess.isalpha():
            print("Enter letters only.")
            continue

        if word_len is None:
            word_len = len(guess)
            current_words = filter_by_length(current_words, word_len)

        if len(guess) != word_len:
            print(f"Guess must be length {word_len}.")
            continue

        gp = input(f"Greens pattern with '.' for unknowns ({word_len} chars), e.g. '.r..e': ").strip()
        if len(gp) != word_len:
            print(f"Pattern must be exactly {word_len} characters.")
            continue
        try:
            greens_update = parse_greens_pattern(gp)
        except ValueError as e:
            print(e)
            continue
        greens.update(greens_update)

        yp = input("Yellows as 'letter@pos' 1-based, space or comma separated (blank if none): ").strip()
        try:
            yellows = parse_yellows(yp, word_len)
        except ValueError as e:
            print(e)
            continue

        # Update constraints from this round
        update_constraints_from_feedback(
            guess=guess,
            greens=greens_update,  # use only this round's greens for count
            yellows=yellows,
            required_min_counts=required_min_counts,
            banned_positions=banned_positions,
            excluded_letters=excluded_letters,
        )

        # Apply all constraints
        current_words = filter_candidates(
            current_words, greens, required_min_counts, banned_positions, excluded_letters
        )

        # Rank and display
        top = score_by_letter_coverage(current_words)[:25]
        print(f"\nCandidates: {len(current_words)}")
        if not current_words:
            print("No matches. Recheck inputs.")
            # allow recovery: reset last updates? Keep simple: continue.
            continue
        for w, s in top:
            print(f"{w}\t{s:.3f}")

        # Optional quick summary
        if required_min_counts:
            mins = ", ".join(f"{k}>={v}" for k, v in sorted(required_min_counts.items()))
        else:
            mins = "(none)"
        banned = ", ".join(f"{ch}@{sorted(list(idxs))}" for ch, idxs in sorted(banned_positions.items()))
        excl = "".join(sorted(excluded_letters)) or "(none)"
        print(f"\nConstraints — greens:{greens}  mins:{mins}  banned:{banned or '(none)'}  exclude:{excl}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Interactive Wordle helper loop.")
    p.add_argument("--file", type=Path, default=Path("valid-wordle-words.txt"),
                   help="Word list file (one word per line).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    words = load_words(args.file, ignore_case=True)
    interactive_loop(words)


if __name__ == "__main__":
    main()
