#!/usr/bin/env python3
"""storyboard-gate — a pre-render gate for narrated-explainer storyboards.

Checks a narrated-explainer script against a measured-exemplar law set BEFORE
any text-to-speech or diffusion render spend:
  hook <= 3s (<= 10 words) at 0:00 -> question <= 25s -> stakes <= 35s
  -> >= 3 build beats -> payoff (show-before-say) -> recap <= 20s,
  zero new information in the close.

The law set (timing ceilings and the narration-rate band) ships as JSON in
laws.default.json and is loaded via the --laws PATH flag, so the gate can be
tuned without touching code.

Input: a JSON storyboard — a list of beats:
  [{"id": "hook", "start_s": 0.0, "text": "...", "kind": "hook|question|stakes|beat|payoff|recap"}, ...]
Or --selftest runs the exemplar's measured structure (must PASS).

Exit 0 = PASS (gate opens, render may proceed). Exit 1 = FAIL (findings listed).
Exit 2 = usage or configuration error.
"""
import json
import os
import re
import sys

KINDS = {"hook", "question", "stakes", "beat", "payoff", "recap"}

NEW_INFO_MARKERS = re.compile(
    r"\b(introduce|new term|additionally|also note|by the way|finally, consider)\b",
    re.I,
)

# Mirror of the shipped laws.default.json. Used only as a fallback when the
# shipped file is missing, so the tool remains self-contained. The shipped
# JSON is the canonical copy; keep the two in sync.
DEFAULT_LAWS = {
    "hook_max_s": 3.0,     # ceiling for the hook's spoken duration (seconds)
    "hook_max_words": 10,  # ceiling for the hook's word count
    "question_max_s": 25.0,  # latest timestamp (s) the question beat may start
    "stakes_max_s": 35.0,    # latest timestamp (s) the stakes beat may start
    "min_beats": 3,          # minimum number of build beats
    "recap_max_s": 20.0,     # ceiling for the recap's spoken duration (seconds)
    "wpm_band": [145, 160],  # measured narration-rate band (words per minute)
}

_DEFAULT_LAWS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "laws.default.json"
)

_INT_FIELDS = ("hook_max_words", "min_beats")
_NUM_FIELDS = ("hook_max_s", "question_max_s", "stakes_max_s", "recap_max_s")


def load_laws(path):
    """Load and validate a law set from a JSON file. Raises on any problem."""
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("laws file must contain a JSON object")
    laws = {}
    for key in DEFAULT_LAWS:
        if key not in data:
            raise ValueError(f"laws file missing required key: {key}")
        laws[key] = data[key]
    for key in _INT_FIELDS:
        if isinstance(laws[key], bool) or not isinstance(laws[key], int):
            raise ValueError(f"laws.{key} must be an integer")
    for key in _NUM_FIELDS:
        if isinstance(laws[key], bool) or not isinstance(laws[key], (int, float)):
            raise ValueError(f"laws.{key} must be a number")
    band = laws["wpm_band"]
    if (
        not isinstance(band, (list, tuple))
        or len(band) != 2
        or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in band)
    ):
        raise ValueError("laws.wpm_band must be a [low, high] pair of numbers")
    return laws


def _default_laws():
    """The default law set: the shipped laws.default.json, else its mirror."""
    try:
        return load_laws(_DEFAULT_LAWS_PATH)
    except OSError:
        return dict(DEFAULT_LAWS)


def check(beats, laws):
    findings = []
    by_kind = {}
    for b in beats:
        k = b.get("kind")
        if k not in KINDS:
            findings.append(f"beat '{b.get('id', '?')}': unknown kind '{k}' (allowed: {sorted(KINDS)})")
            continue
        by_kind.setdefault(k, []).append(b)

    def first(kind):
        return by_kind.get(kind, [None])[0]

    # 1. Hook timing + length
    hook = first("hook")
    if not hook:
        findings.append("no hook beat — the measured exemplar requires a hook at 0:00")
    else:
        if hook.get("start_s", 999) > 0.0:
            findings.append(f"hook must start at 0.0s (got {hook['start_s']}s)")
        hook_words = len(hook.get("text", "").split())
        if hook_words > laws["hook_max_words"]:
            findings.append(f"hook is {hook_words} words (max {laws['hook_max_words']})")
        est_s = hook.get("dur_s") or hook_words / 2.45  # ~147 wpm ~= 2.45 words/s
        if est_s > laws["hook_max_s"]:
            findings.append(f"hook est. {est_s:.1f}s > {laws['hook_max_s']}s ({hook_words} words)")

    # 2. Question <= question_max_s, stakes <= stakes_max_s
    q = first("question")
    if not q:
        findings.append("no question beat — the video must state its question in plain words")
    elif q.get("start_s", 999) > laws["question_max_s"]:
        findings.append(f"question lands at {q['start_s']}s (max {laws['question_max_s']}s)")
    s = first("stakes")
    if not s:
        findings.append("no stakes beat — why it matters must be stated")
    elif s.get("start_s", 999) > laws["stakes_max_s"]:
        findings.append(f"stakes land at {s['start_s']}s (max {laws['stakes_max_s']}s)")

    # 3. Build beats >= min_beats
    n_beats = len(by_kind.get("beat", []))
    if n_beats < laws["min_beats"]:
        findings.append(f"only {n_beats} build beats (min {laws['min_beats']} escalating beats)")

    # 4. Payoff present, before recap
    p = first("payoff")
    r = first("recap")
    if not p:
        findings.append("no payoff beat — the answer must land (show before say)")
    if p and r and p["start_s"] >= r["start_s"]:
        findings.append("payoff must precede recap")

    # 5. Recap: <= recap_max_s, zero new information
    if r:
        r_words = len(r.get("text", "").split())
        est = r.get("dur_s") or r_words / 2.45
        if est > laws["recap_max_s"]:
            findings.append(f"recap est. {est:.1f}s > {laws['recap_max_s']}s")
        if NEW_INFO_MARKERS.search(r.get("text", "")):
            findings.append("recap introduces new information — the close carries zero new terms")

    # 6. Narration rate: summed spoken duration (words/2.45 per beat), NOT
    #    timeline span — partial storyboards rate-check on what's actually
    #    scripted, not the gaps between beats.
    total_words = sum(len(b.get("text", "").split()) for b in beats)
    total_s = sum((b.get("dur_s") or len(b.get("text", "").split()) / 2.45) for b in beats)
    if total_s > 0 and total_words > 0:
        wpm = total_words / (total_s / 60)
        lo, hi = laws["wpm_band"]
        if wpm and (wpm < lo - 25 or wpm > hi + 25):
            findings.append(f"narration rate est. {wpm:.0f} wpm — far outside the {lo}-{hi} band")

    return findings


def selftest(laws):
    """The exemplar's measured structure — the gate must PASS its own calibration source."""
    selftest_beats = [
        {"id": "hook", "kind": "hook", "start_s": 0.0, "text": "Here's something every calculus student learns."},
        {"id": "deriv", "kind": "beat", "start_s": 2.8, "text": "Zoom in far enough on a smooth curve, and it starts to look like a straight line. That straight line is the derivative."},
        {"id": "stock", "kind": "beat", "start_s": 10.0, "text": "Now, here's a stock price. Zoom in, and it's just as jagged as before."},
        {"id": "noslope", "kind": "beat", "start_s": 17.1, "text": "This curve has no slope anywhere."},
        {"id": "question", "kind": "question", "start_s": 19.7, "text": "So how do you do calculus on something with no derivative?"},
        {"id": "sc", "kind": "beat", "start_s": 23.9, "text": "That's what stochastic calculus is for."},
        {"id": "stakes", "kind": "stakes", "start_s": 29.1, "text": "And its answer has one surprising twist. A twist that ends up pricing trillions of dollars of options."},
        {"id": "build", "kind": "beat", "start_s": 35.1, "text": "Let's build the simplest jagged curve. Flip a coin. Heads step up. Tails step down."},
        # full-arc tail: payoff at ~3:45, recap+close at ~4:20 (measured exemplar timings)
        {"id": "payoff", "kind": "payoff", "start_s": 225.0, "text": "When noise scales like the square root of time, its square doesn't vanish. It becomes time."},
        {"id": "recap", "kind": "recap", "start_s": 268.4, "text": "And the second-order term you were taught to ignore becomes the drift you can't afford to."},
    ]
    return check(selftest_beats, laws)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    laws_path = None
    storyboard_path = None
    selftest_flag = False

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--selftest":
            selftest_flag = True
        elif a == "--laws":
            i += 1
            if i >= len(argv):
                print("error: --laws requires a path", file=sys.stderr)
                return 2
            laws_path = argv[i]
        elif a.startswith("--laws="):
            laws_path = a.split("=", 1)[1]
        elif a.startswith("-"):
            print(f"error: unknown option: {a}", file=sys.stderr)
            print(__doc__)
            return 2
        else:
            storyboard_path = a
        i += 1

    if laws_path:
        try:
            laws = load_laws(laws_path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"error loading laws file: {e}", file=sys.stderr)
            return 2
    else:
        laws = _default_laws()

    if selftest_flag:
        findings = selftest(laws)
        if findings:
            print("SELFTEST FAIL — the gate rejected its own calibration source:")
            for x in findings:
                print(" -", x)
            return 1
        print("SELFTEST PASS — the exemplar's measured structure clears the gate.")
        return 0

    if not storyboard_path:
        print(__doc__)
        return 2

    try:
        with open(storyboard_path) as fh:
            beats = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error reading storyboard: {e}", file=sys.stderr)
        return 2

    findings = check(beats, laws)
    if findings:
        print(f"STORYBOARD GATE: FAIL — {len(findings)} finding(s) (render blocked before TTS/diffusion spend):")
        for x in findings:
            print(" -", x)
        return 1
    print(f"STORYBOARD GATE: PASS — {len(beats)} beats clear the gate (render may proceed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
