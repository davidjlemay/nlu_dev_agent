---
name: jsgf-coverage
description: Check utterance coverage for a JSGF rule from the command line.
---

# jsgf-coverage

Check utterance coverage for a JSGF rule from the command line.

## Usage

```bash
.venv/bin/python3 skills/jsgf-coverage/coverage.py <rule> <file.jsgf> \
    --utterances '["utterance 1", "utterance 2"]'

# Or from a file (one utterance per line)
.venv/bin/python3 skills/jsgf-coverage/coverage.py <rule> <file.jsgf> \
    --utterances-file test/utterances.txt
```

## Examples

```bash
# Check inline utterances
.venv/bin/python3 skills/jsgf-coverage/coverage.py greeting grammars/greeting.jsgf \
    --utterances '["hello", "hi", "good morning"]'

# Check from file
.venv/bin/python3 skills/jsgf-coverage/coverage.py transfer grammars/transfer.jsgf \
    --utterances-file tests/utterances/transfer.txt
```

## Output

```json
{
  "rule": "greeting",
  "file": "/path/to/greeting.jsgf",
  "coverage_ratio": 0.67,
  "covered": ["hello", "hi"],
  "uncovered": ["good morning"]
}
```

## Notes
- Uses pyjsgf `Rule.matches()` — exact string matching only
- `coverage_ratio == 1.0` means all utterances are matched
- Use `uncovered` list to identify gaps in the grammar
