# jsgf-context

Get generation context for a target JSGF file before generating a new rule.

## Usage

```bash
python skills/jsgf-context/context.py grammars/transfer.jsgf \
  --intent "Transfer funds between accounts" \
  --examples '["transfer 100 to savings", "move money to chequing"]'
```

| Argument | Default | Description |
|---|---|---|
| `file` | — | Target `.jsgf` file (need not exist yet) |
| `--intent` | `""` | Natural language description of the intent |
| `--examples` | `[]` | JSON array of example utterances |
| `--workspace` | Parent dir of file | Workspace root |

## Output

```json
{
  "existing_rules": [
    {
      "name": "amount",
      "file": "/path/grammars/shared.jsgf",
      "visible": true,
      "dependencies": ["cardinal"],
      "dependents": [],
      "example_utterances": ["100", "fifty dollars"]
    }
  ],
  "dialect_functions": [
    {
      "name": "normalise",
      "parameters": [{"name": "value", "type": "rule_ref", "optional": false},
                     {"name": "unit", "type": "string", "optional": false}],
      "return_type": "expansion",
      "doc": "Normalises numeric value to canonical form."
    }
  ],
  "similar_rules": [...],
  "import_suggestions": ["/path/grammars/shared.jsgf"]
}
```

## When to use

**Always call `jsgf-context` before generating a new rule.** It tells you:

1. Which rules already exist and can be reused or imported
2. Which dialect functions are available
3. Which existing rules partially cover your examples (reuse candidates)
4. Which files to import to avoid duplicating shared vocabulary

## Notes

- `similar_rules` only includes rules with >30% coverage of your example utterances
- The target file need not exist; context is assembled from the rest of the workspace
