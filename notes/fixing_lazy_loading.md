 Bugs fixed

  1. _find_dialect_cfg — skills couldn't find jsgf-dialect.json (root cause)

  Files: skills/jsgf-coverage/coverage.py, skills/jsgf-context/context.py, skills/jsgf-generate/generate.py

  The skills set workspace = file_path.parent (e.g. grammars/) then looked for jsgf-dialect.json only in that directory. Since the config lives at the project root, they always fell back to
  DialectRegistry.standard() (no data sources), so all $lookup() calls returned []. Fixed by adding _find_dialect_cfg() that walks up the directory tree. Also passes the found root as data_root to DataLoader
  so relative data paths resolve correctly.

  2. Case-insensitive expansion-set matching

  File: agent/api.py

  The expansion-set path for validate_coverage compared exact strings. Loaded vocabulary items use their original casing ("TD Canada-Trust", "BMO") while ASR utterances are lowercase. Fixed by lowercasing all
   expansions into the set and comparing utterance.lower() against it.

  3. Transitive func_placeholders check

  File: agent/api.py

  use_expansion_path only triggered when the grammar file being validated directly contained $lookup() calls. Rules that import a rule with $lookup() (e.g. check_balance importing bank_name) were silently
  using the regex matches() path, which can't handle plhdr0 tokens. Fixed with _any_has_placeholders() that walks the import graph.

  4. Depth limit too shallow for imported grammars

  File: agent/api.py

  _generate_expansions had a depth limit of 6. A multi-file grammar like check_balance → account_type_only → account_type → RequiredGrouping → AlternativeSet → Literal requires depth 7 through imports.
  Literals inside nested imported rules silently returned nothing, making those alternatives produce zero expansions. Increased to 12.

  5. Default expansion_limit too small for compound rules

  File: jsgf-dialect.json

  The default budget of 200 was exhausted by early alternatives before reaching compound rules (e.g. account_type_bank_name with 1848 combinations). Raised to 5000.
