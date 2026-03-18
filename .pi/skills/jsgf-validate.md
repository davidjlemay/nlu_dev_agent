---
name: jsgf-validate
description: Validate a JSGF grammar file from the command line (without the interactive agent).
---

# jsgf-validate

Validate a JSGF grammar file from the command line (without the interactive agent).

## Usage

```bash
.venv/bin/python3 skills/jsgf-validate/validate.py <file.jsgf> [--workspace <dir>]
```

## Examples

```bash
# Validate a single file
.venv/bin/python3 skills/jsgf-validate/validate.py grammars/transfer.jsgf

# Validate with explicit workspace root
.venv/bin/python3 skills/jsgf-validate/validate.py grammars/transfer.jsgf --workspace .
```

## Output

```json
{
  "file": "/path/to/transfer.jsgf",
  "valid": false,
  "diagnostics": [
    { "line": 4, "character": 8, "severity": "error", "message": "Undefined rule: <unknownRule>" }
  ]
}
```

## Notes
- Exit code 0 whether or not there are diagnostics; check `valid` field
- `--workspace` defaults to the file's parent directory
- The validator re-indexes all `.jsgf` files in the workspace directory
