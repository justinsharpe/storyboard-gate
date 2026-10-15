# storyboard-gate

A pre-render gate for narrated-explainer storyboards: validate the script's
structure and timing before spending anything on text-to-speech or image
generation.

## Why this exists

Rendering narration and visuals is the expensive part of producing a narrated
explainer. The structural mistakes that ruin one — a hook that drags, a
question that never lands, a recap that sneaks in new information — are all
detectable for free, from the storyboard alone, before any render spend. This
tool is that cheap gate: it reads a storyboard, checks it against a
measured-exemplar law set (timing ceilings derived from what actually works),
and refuses to let render proceed until the script clears.

The idea is simple and portable: **validate the storyboard BEFORE spending on
render.** One script, one JSON config, zero dependencies.

## The law set

The gate checks against a small set of timing laws. Every law is a named field
in a JSON config file (see `laws.default.json` for the shipped default):

| Field            | Type        | Meaning                                                                 |
|------------------|-------------|-------------------------------------------------------------------------|
| `hook_max_s`     | number      | Ceiling (seconds) for the hook's spoken duration. The hook must also start at 0:00. |
| `hook_max_words` | integer     | Ceiling for the hook's word count.                                      |
| `question_max_s` | number      | Latest timestamp (seconds) at which the question beat may start.        |
| `stakes_max_s`   | number      | Latest timestamp (seconds) at which the stakes beat may start.          |
| `min_beats`      | integer     | Minimum number of build beats (escalating middle section).              |
| `recap_max_s`    | number      | Ceiling (seconds) for the recap's spoken duration.                      |
| `wpm_band`       | [low, high] | Narration-rate band (words per minute). Rate far outside this band fails. |

Beat `kind` must be one of: `hook`, `question`, `stakes`, `beat`, `payoff`,
`recap`.

The gate enforces the measured structure: hook at 0:00 → question by its
ceiling → stakes by their ceiling → at least the minimum build beats → payoff
(show before say) → recap under its ceiling with zero new information. The
narration rate is estimated from summed spoken duration (words at ~147 wpm),
not timeline span, so partial storyboards are checked on what is actually
scripted rather than the gaps between beats.

## Usage

```sh
# Validate a storyboard against the shipped default law set
python3 storyboard_gate.py storyboard.json

# Validate against a custom law set
python3 storyboard_gate.py --laws my-laws.json storyboard.json

# Run the self-test against the default law set
python3 storyboard_gate.py --selftest
```

Exit codes: `0` PASS (render may proceed), `1` FAIL (findings printed),
`2` usage or configuration error.

When `--laws` is omitted, the tool loads `laws.default.json` from alongside the
script (falling back to an in-code mirror of the same values if the file is
missing). A custom file must contain every field in the table above; the loader
rejects missing or mistyped fields before any check runs.

### Storyboard input format

A JSON array of beats:

```json
[
  {"id": "hook", "kind": "hook", "start_s": 0.0, "text": "..."},
  {"id": "q", "kind": "question", "start_s": 19.7, "text": "..."},
  {"id": "s", "kind": "stakes", "start_s": 29.1, "text": "..."},
  {"id": "b1", "kind": "beat", "start_s": 35.1, "text": "..."},
  {"id": "p", "kind": "payoff", "start_s": 225.0, "text": "..."},
  {"id": "r", "kind": "recap", "start_s": 268.4, "text": "..."}
]
```

Each beat takes an optional `dur_s` (explicit spoken duration, seconds); when
absent it is estimated from word count.

## Self-test

`--selftest` runs the exemplar whose measured structure the law set was derived
from. It must PASS against the default law set — a failing self-test means the
config or the gate itself is broken.

## Dependencies

Python 3 standard library only (`json`, `os`, `re`, `sys`). Works on macOS,
Linux, and Windows.

## License

MIT — see [LICENSE](LICENSE).
