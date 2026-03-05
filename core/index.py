"""
GrammarIndex: workspace-level graph of all grammar files.

Maintains:
- path → GrammarDocument
- rule_name → defining Path (within its grammar namespace)
- grammar_name → Path (for import resolution)
- forward import graph (path → set[Path])
- reverse dependent graph (path → set[Path])

Import resolution follows JSGF conventions:
  import <com.example.shared.*>   →  grammar named 'com.example.shared'
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import ImportInfo

from .document import GrammarDocument, RuleInfo
from .dialect import DialectRegistry


@dataclass
class RuleLocation:
    file: Path
    rule: RuleInfo


class GrammarIndex:
    def __init__(self, workspace_root: Path, dialect: DialectRegistry):
        self.root = workspace_root
        self.dialect = dialect
        self._documents: dict[Path, GrammarDocument] = {}
        # rule_name → defining file  (last writer wins within same grammar ns)
        self._rule_index: dict[str, Path] = {}
        # grammar_name → file path
        self._grammar_name_index: dict[str, Path] = {}
        # forward: file → set of files it imports
        self._imports: dict[Path, set[Path]] = {}
        # reverse: file → set of files that import it
        self._dependents: dict[Path, set[Path]] = {}

    # ------------------------------------------------------------------ #
    #  Workspace bootstrap                                                 #
    # ------------------------------------------------------------------ #

    def index_workspace(self) -> None:
        """Scan workspace root for all .gram / .jsgf files and index them."""
        for ext in ('*.gram', '*.jsgf', '*.jgram'):
            for path in self.root.rglob(ext):
                try:
                    self.update_file(path, path.read_text(encoding='utf-8'))
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    #  Incremental updates                                                 #
    # ------------------------------------------------------------------ #

    def update_file(self, path: Path, source: str) -> set[Path]:
        """
        Parse *path* with *source* and update all index structures.
        Returns the set of affected paths (path itself + its dependents)
        that need diagnostics re-run.
        """
        doc = GrammarDocument.parse(path, source)
        self._documents[path] = doc
        self._reindex_rules(path, doc)
        self._reindex_grammar_name(path, doc)
        affected = self._update_import_graph(path, doc)
        # Pre-resolve imports for all affected documents so Rule.matches() works
        for aff_path in affected:
            aff_doc = self._documents.get(aff_path)
            if aff_doc:
                self.pre_resolve_grammar_imports(aff_doc)
        return affected

    def remove_file(self, path: Path) -> set[Path]:
        """Remove a file from the index and return affected dependents."""
        affected = self._dependents.get(path, set()).copy()
        self._documents.pop(path, None)
        self._cleanup_rule_index(path)
        self._cleanup_grammar_name_index(path)
        # Clean up import graph
        old_imports = self._imports.pop(path, set())
        for imp_path in old_imports:
            self._dependents.get(imp_path, set()).discard(path)
        return affected

    # ------------------------------------------------------------------ #
    #  Resolution                                                          #
    # ------------------------------------------------------------------ #

    def resolve_rule(self, name: str, from_file: Path) -> RuleLocation | None:
        """
        Resolve rule *name* visible from *from_file*.
        Checks local rules first, then imported rules.
        """
        # Check local file
        doc = self._documents.get(from_file)
        if doc:
            rule = doc.get_rule(name)
            if rule:
                return RuleLocation(file=from_file, rule=rule)

        # Check directly imported files
        for imp_path in self._imports.get(from_file, set()):
            imp_doc = self._documents.get(imp_path)
            if imp_doc is None:
                continue
            rule = imp_doc.get_rule(name)
            if rule and rule.visible:
                return RuleLocation(file=imp_path, rule=rule)

        return None

    def resolve_rules(self, name: str, from_file: Path) -> list[RuleLocation]:
        """
        Return all variants of *name* visible from *from_file* (local then imported).

        A variant is any rule whose original name or pyjsgf_name equals *name*,
        so both ``'noun'`` and ``'noun__number_singular'`` work as lookup keys.
        """
        results: list[RuleLocation] = []
        doc = self._documents.get(from_file)
        if doc:
            for rule in doc.rules:
                if rule.name == name or rule.pyjsgf_name == name:
                    results.append(RuleLocation(file=from_file, rule=rule))
        if not results:
            for imp_path in self._imports.get(from_file, set()):
                imp_doc = self._documents.get(imp_path)
                if imp_doc:
                    for rule in imp_doc.rules:
                        if (rule.name == name or rule.pyjsgf_name == name) and rule.visible:
                            results.append(RuleLocation(file=imp_path, rule=rule))
        return results

    def resolve_import(self, imp: ImportInfo, from_file: Path) -> Path | None:
        """
        Return the path of the grammar that satisfies *imp*, or None.
        """
        target = self._grammar_name_index.get(imp.grammar_name)
        if target is None:
            return None
        if imp.wildcard:
            return target
        # Specific rule import: check the rule is public in that grammar
        target_doc = self._documents.get(target)
        if target_doc is None:
            return None
        rule = target_doc.get_rule(imp.rule_name)
        if rule and rule.visible:
            return target
        return None

    def get_visible_rules(self, from_file: Path) -> list[RuleLocation]:
        """All rules accessible from *from_file* (local + public imported)."""
        visible: list[RuleLocation] = []
        doc = self._documents.get(from_file)
        if doc:
            for rule in doc.rules:
                visible.append(RuleLocation(file=from_file, rule=rule))
        for imp_path in self._imports.get(from_file, set()):
            imp_doc = self._documents.get(imp_path)
            if imp_doc:
                for rule in imp_doc.rules:
                    if rule.visible:
                        visible.append(RuleLocation(file=imp_path, rule=rule))
        return visible

    def get_all_rules(self) -> list[RuleLocation]:
        """All rules across the entire workspace."""
        result: list[RuleLocation] = []
        for path, doc in self._documents.items():
            for rule in doc.rules:
                result.append(RuleLocation(file=path, rule=rule))
        return result

    def build_pyjsgf_memo(self) -> dict:
        """
        Build a grammar-name → pyjsgf.Grammar memo dictionary.

        Pass this to pyjsgf's Grammar.resolve_imports(memo) before calling
        Rule.matches() on any rule that may reference imported rules.
        This prevents pyjsgf from scanning the filesystem for grammar files.
        """
        memo: dict = {}
        for doc in self._documents.values():
            if doc.pyjsgf_grammar is not None and doc.grammar_name:
                memo[doc.grammar_name] = doc.pyjsgf_grammar
        return memo

    def pre_resolve_grammar_imports(self, doc: 'GrammarDocument') -> None:
        """
        Pre-resolve imports for *doc*'s pyjsgf Grammar using the workspace index.
        This must be called before using Rule.matches() on any rule that imports
        rules from other grammars.
        """
        if doc.pyjsgf_grammar is None:
            return
        memo = self.build_pyjsgf_memo()
        try:
            doc.pyjsgf_grammar.resolve_imports(memo)
        except Exception:
            pass  # Best-effort; unresolvable imports are reported as diagnostics

    def is_library(self, path: Path) -> bool:
        """Return True if *path* is imported by at least one other document."""
        return bool(self._dependents.get(path))

    def find_references(self, rule_name: str) -> list[tuple[Path, list]]:
        """
        Find all files that reference *rule_name*.
        Returns list of (file_path, [Position, ...]).
        """
        results: list[tuple[Path, list]] = []
        for path, doc in self._documents.items():
            positions = doc.ref_positions.get(rule_name)
            if positions:
                results.append((path, positions))
        return results

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _reindex_rules(self, path: Path, doc: GrammarDocument) -> None:
        # Remove all old entries pointing to this file
        self._rule_index = {k: v for k, v in self._rule_index.items() if v != path}
        for rule in doc.rules:
            self._rule_index[rule.name] = path

    def _reindex_grammar_name(self, path: Path, doc: GrammarDocument) -> None:
        # Remove old entry for this file
        self._grammar_name_index = {
            k: v for k, v in self._grammar_name_index.items() if v != path
        }
        if doc.grammar_name:
            self._grammar_name_index[doc.grammar_name] = path

    def _update_import_graph(
        self, path: Path, doc: GrammarDocument
    ) -> set[Path]:
        """
        Update forward/reverse import edges for *path*.
        Returns the set of affected files.
        """
        # Remove old forward edges from path
        old_imports = self._imports.pop(path, set())
        for old_imp_path in old_imports:
            self._dependents.get(old_imp_path, set()).discard(path)

        # Resolve new imports
        new_imports: set[Path] = set()
        for imp in doc.imports:
            target = self._grammar_name_index.get(imp.grammar_name)
            if target and target != path:
                new_imports.add(target)

        self._imports[path] = new_imports
        for imp_path in new_imports:
            self._dependents.setdefault(imp_path, set()).add(path)

        return {path} | self._dependents.get(path, set())

    def _cleanup_rule_index(self, path: Path) -> None:
        self._rule_index = {k: v for k, v in self._rule_index.items() if v != path}

    def _cleanup_grammar_name_index(self, path: Path) -> None:
        self._grammar_name_index = {
            k: v for k, v in self._grammar_name_index.items() if v != path
        }
