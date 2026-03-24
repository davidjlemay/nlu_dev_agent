  Root cause: Two separate bugs:

  1. Import ordering — index_workspace() processes files sequentially. If check_balance.jsgf was indexed before shared_banking.jsgf, the import edge was never created (shared_banking wasn't in the grammar
  name index yet), so pre_resolve_grammar_imports couldn't inject the imported rules. Fixed by adding a second pass in index_workspace() that rebuilds all import edges and re-resolves all grammars after every
   file has been parsed.
  2. Name mangling mismatch — shared_banking.jsgf's account_type {slot:string=account_type} gets mangled to account_type__slot_account_type in pyjsgf. But check_balance.jsgf references <account_type>
  (original name). pyjsgf's get_rule_from_name('account_type') couldn't find account_type__slot_account_type. Fixed by _inject_original_name_aliases(): after import resolution, alias Rule objects with
  original names (and deep-copied expansions) are added directly to the importing grammar's _rules, enabling cross-file matches().

  LSP warning added via validate_import_aliases() in core/validator.py — reports a Warning diagnostic on the import statement when a local rule name collides with an imported LHS-flag rule's original name
  (which would prevent the alias from being injected and break cross-file matching).
