# jsgf-validate

Validate a JSGF grammar file against the workspace index.

## Usage

```
python skills/jsgf-validate/validate.py <file.gram> [--workspace <dir>]
```

| Argument | Default | Description |
|---|---|---|
| `file` | — | Path to the `.gram` (or `.jsgf`) file to validate |
| `--workspace` | Parent dir of file | Workspace root; used to find other grammars and `jsgf-dialect.json` |

## Output

JSON on stdout:

```json
{
  "file": "/path/to/file.gram",
  "valid": false,
  "diagnostics": [
    {
      "line": 4,
      "character": 8,
      "severity": "error",
      "message": "Undefined rule: <unknownRule>"
    }
  ]
}
```

## Diagnostic types

| Severity | Condition |
|---|---|
| `error` | Parse failure, undefined rule reference, duplicate rule name |
| `error` | Dialect: unknown function, wrong argument count, disallowed flag type |
| `warning` | Import cannot be resolved to a file in the workspace |

## When to use

- After any grammar edit to catch errors before commit
- In the agentic correction loop to validate generated grammars
- As a pre-commit check in CI

## Notes

- The validator re-indexes the entire workspace from `--workspace` on each call.
  For large workspaces, prefer the LSP server (which maintains an in-memory index)
  and call this tool only for batch/CI checks.
- Exit code is 0 whether or not diagnostics are found; check `valid` in JSON output.
