 Summary

 ### 1. New feature: Flagged body references (core/document.py)

 Grammar authors can now pin a specific variant in rule bodies using inline flags:

 ```jsgf
   <det> {gender:enum=masculine} = le;
   <det> {gender:enum=feminine}  = la;

   // Pin to masculine — only matches "le"
   public <masc_phrase> = <det> {gender:enum=masculine} chat;

   // Bare reference — matches either "le" or "la" (engine resolves)
   public <any_phrase> = <det> chat;
 ```

 Implementation — A new _FLAGGED_REF_RE pass in _mangle_source() detects <name> {flags} patterns in rule bodies (distinguished from declarations by the absence of a trailing =). When the flagged reference
 resolves to a known mangled declaration, it's rewritten (e.g., <det> {gender:enum=masculine} → <det__gender_masculine>) and the inline flags are consumed. Unknown variants are left unchanged for diagnostic
 reporting.

 Resolution order in _mangle_source:
 1. Declarations mangled (_LHS_DECL_RE)
 2. Flagged body references resolved to specific mangled variants (_FLAGGED_REF_RE)
 3. Bare references — unambiguous (1 variant) rewritten directly; ambiguous (multiple variants) resolved via synthetic union rules

 ### 2. System prompt updated (.pi/SYSTEM.md)

 Added a "Bare vs flagged body references" subsection explaining both forms with examples and guidance on when to use each.

 ### 3. New tests (tests/test_document.py)

 ┌──────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────┐
 │ Test                                                     │ Asserts                                                                    │
 ├──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
 │ test_mangle_source_flagged_body_reference                │ <noun> {number:enum=plural} → <noun__number_plural>, inline flags consumed │
 ├──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────┤
 │ test_mangle_source_flagged_ref_unknown_variant_ambiguous │ Non-existent variant (dual) leaves bare <noun> for synthetic union         │
 └──────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────┘

 All 72 tests pass.
