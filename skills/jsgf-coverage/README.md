# jsgf-coverage

Check whether a JSGF rule matches a list of test utterances.

## Usage

```bash
# Inline utterances (JSON array)
python skills/jsgf-coverage/coverage.py greeting grammars/intents.gram \
  --utterances '["hello", "hi", "good morning"]'

# Utterances from a file (one per line)
python skills/jsgf-coverage/coverage.py greeting grammars/intents.gram \
  --utterances-file test/utterances/greeting.txt
```

| Argument | Default | Description |
|---|---|---|
| `rule` | — | Rule name without `<>` |
| `file` | — | Path to the `.gram` file |
| `--utterances` | — | JSON array of utterance strings |
| `--utterances-file` | — | Path to a file with one utterance per line |
| `--workspace` | Parent dir of file | Workspace root |

## Output

```json
{
  "rule": "greeting",
  "file": "/path/to/intents.gram",
  "coverage_ratio": 0.67,
  "covered": ["hello", "hi"],
  "uncovered": ["good morning"]
}
```

## When to use

- After generating a grammar rule, verify it matches all required utterances
- During the agentic correction loop to identify gaps
- Regression testing: pipe `uncovered` list into a bug report

## Notes

- Uses pyjsgf `Rule.matches()` for matching — exact string matching, no fuzzy
- A rule must be visible (`public`) to match utterances from an external file
- If `coverage_ratio` is less than 1.0, the `uncovered` list shows what to fix
