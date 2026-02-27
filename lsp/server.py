"""
JSGF Language Server — pygls 2.x entry point.

Features:
- textDocument/didOpen, didChange, didClose  → diagnostics push
- textDocument/completion                    → rule names + dialect functions
- textDocument/definition                    → go-to rule definition
- textDocument/references                    → find all references
- textDocument/rename                        → rename rule across workspace
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

# Ensure the project root is on sys.path when run as a script
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.dialect import DialectRegistry
from core.document import GrammarDocument, _pos_to_range
from core.index import GrammarIndex, RuleLocation
from core.patch import Position
from core.validator import validate_dialect

# ------------------------------------------------------------------ #
#  Server singleton                                                    #
# ------------------------------------------------------------------ #

server = LanguageServer(
    name='jsgf-lsp',
    version='v0.1',
    text_document_sync_kind=lsp.TextDocumentSyncKind.Full,
)

index: GrammarIndex | None = None


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _uri_to_path(uri: str) -> Path:
    if uri.startswith('file://'):
        uri = uri[len('file://'):]
    return Path(uri)


def _path_to_uri(path: Path) -> str:
    return path.as_uri()


def _sync_and_publish(ls: LanguageServer, uri: str, source: str) -> None:
    if index is None:
        return
    path = _uri_to_path(uri)
    affected = index.update_file(path, source)
    for aff_path in affected:
        doc = index._documents.get(aff_path)
        if doc is None:
            continue
        diags = doc.get_diagnostics(index)
        diags += validate_dialect(doc, index.dialect)
        ls.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(
            uri=_path_to_uri(aff_path),
            diagnostics=diags,
        ))


def _word_at(source: str, line: int, character: int) -> str | None:
    """Extract the rule name at the given cursor position, if any."""
    import re
    lines = source.splitlines()
    if line >= len(lines):
        return None
    row = lines[line]
    # Look for <ruleName> at character
    for m in re.finditer(r'<([A-Za-z0-9_.$-]+)>', row):
        if m.start() <= character <= m.end():
            return m.group(1)
    return None


# ------------------------------------------------------------------ #
#  Lifecycle                                                           #
# ------------------------------------------------------------------ #

@server.feature(lsp.INITIALIZE)
def on_initialize(ls: LanguageServer, params: lsp.InitializeParams):
    global index
    root_uri = (
        params.root_uri
        or (params.workspace_folders[0].uri if params.workspace_folders else None)
    )
    if root_uri:
        root = _uri_to_path(root_uri)
    else:
        root = Path.cwd()

    dialect_cfg = root / 'jsgf-dialect.json'
    dialect = (
        DialectRegistry.from_config(dialect_cfg)
        if dialect_cfg.exists()
        else DialectRegistry.standard()
    )
    index = GrammarIndex(root, dialect)
    index.index_workspace()


# ------------------------------------------------------------------ #
#  Text document sync                                                  #
# ------------------------------------------------------------------ #

@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: lsp.DidOpenTextDocumentParams):
    _sync_and_publish(ls, params.text_document.uri, params.text_document.text)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: LanguageServer, params: lsp.DidChangeTextDocumentParams):
    if params.content_changes:
        text = params.content_changes[-1].text
        _sync_and_publish(ls, params.text_document.uri, text)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: lsp.DidCloseTextDocumentParams):
    # Clear diagnostics for the closed file
    ls.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(
        uri=params.text_document.uri,
        diagnostics=[],
    ))


# ------------------------------------------------------------------ #
#  Completion                                                          #
# ------------------------------------------------------------------ #

@server.feature(
    lsp.TEXT_DOCUMENT_COMPLETION,
    lsp.CompletionOptions(trigger_characters=['<', '$']),
)
def completion(
    ls: LanguageServer,
    params: lsp.CompletionParams,
) -> lsp.CompletionList:
    if index is None:
        return lsp.CompletionList(is_incomplete=False, items=[])

    path = _uri_to_path(params.text_document.uri)
    items: list[lsp.CompletionItem] = []

    # Rule name completions
    for loc in index.get_visible_rules(path):
        label = f'<{loc.rule.name}>'
        items.append(lsp.CompletionItem(
            label=label,
            kind=lsp.CompletionItemKind.Function,
            detail=f'Defined in {loc.file.name}',
        ))

    # Dialect function completions
    for fn_name, fn in index.dialect.functions.items():
        params_str = ', '.join(p.name for p in fn.parameters)
        items.append(lsp.CompletionItem(
            label=f'${fn_name}()',
            kind=lsp.CompletionItemKind.Function,
            detail=f'Dialect function → {fn.return_type}',
            documentation=fn.doc or None,
            insert_text=f'${fn_name}({params_str})',
        ))

    return lsp.CompletionList(is_incomplete=False, items=items)


# ------------------------------------------------------------------ #
#  Go-to definition                                                    #
# ------------------------------------------------------------------ #

@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def definition(
    ls: LanguageServer,
    params: lsp.DefinitionParams,
) -> Optional[lsp.Location]:
    if index is None:
        return None

    path = _uri_to_path(params.text_document.uri)
    doc = index._documents.get(path)
    if doc is None:
        return None

    rule_name = _word_at(
        doc.source,
        params.position.line,
        params.position.character,
    )
    if rule_name is None:
        return None

    loc = index.resolve_rule(rule_name, path)
    if loc is None:
        return None

    def_pos = loc.rule.file_doc.def_positions.get(rule_name) if hasattr(loc.rule, 'file_doc') else None
    # Look up from the document
    target_doc = index._documents.get(loc.file)
    if target_doc is None:
        return None
    pos = target_doc.def_positions.get(rule_name, Position(0, 0))
    return lsp.Location(
        uri=_path_to_uri(loc.file),
        range=_pos_to_range(pos, len(rule_name)),
    )


# ------------------------------------------------------------------ #
#  Find references                                                     #
# ------------------------------------------------------------------ #

@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
def references(
    ls: LanguageServer,
    params: lsp.ReferenceParams,
) -> list[lsp.Location]:
    if index is None:
        return []

    path = _uri_to_path(params.text_document.uri)
    doc = index._documents.get(path)
    if doc is None:
        return []

    rule_name = _word_at(
        doc.source,
        params.position.line,
        params.position.character,
    )
    if rule_name is None:
        return []

    locations: list[lsp.Location] = []
    for ref_path, positions in index.find_references(rule_name):
        for pos in positions:
            locations.append(lsp.Location(
                uri=_path_to_uri(ref_path),
                range=_pos_to_range(pos, len(rule_name)),
            ))

    if params.context.include_declaration:
        loc = index.resolve_rule(rule_name, path)
        if loc:
            target_doc = index._documents.get(loc.file)
            if target_doc:
                def_pos = target_doc.def_positions.get(rule_name, Position(0, 0))
                locations.insert(0, lsp.Location(
                    uri=_path_to_uri(loc.file),
                    range=_pos_to_range(def_pos, len(rule_name)),
                ))

    return locations


# ------------------------------------------------------------------ #
#  Rename                                                              #
# ------------------------------------------------------------------ #

@server.feature(lsp.TEXT_DOCUMENT_RENAME)
def rename(
    ls: LanguageServer,
    params: lsp.RenameParams,
) -> Optional[lsp.WorkspaceEdit]:
    if index is None:
        return None

    path = _uri_to_path(params.text_document.uri)
    doc = index._documents.get(path)
    if doc is None:
        return None

    rule_name = _word_at(
        doc.source,
        params.position.line,
        params.position.character,
    )
    if rule_name is None:
        return None

    new_name = params.new_name
    changes: dict[str, list[lsp.TextEdit]] = {}

    # Rename definition
    loc = index.resolve_rule(rule_name, path)
    if loc:
        target_doc = index._documents.get(loc.file)
        if target_doc:
            def_pos = target_doc.def_positions.get(rule_name, Position(0, 0))
            uri = _path_to_uri(loc.file)
            changes.setdefault(uri, []).append(lsp.TextEdit(
                range=_pos_to_range(def_pos, len(rule_name)),
                new_text=new_name,
            ))

    # Rename all references
    for ref_path, positions in index.find_references(rule_name):
        uri = _path_to_uri(ref_path)
        for pos in positions:
            changes.setdefault(uri, []).append(lsp.TextEdit(
                range=_pos_to_range(pos, len(rule_name)),
                new_text=new_name,
            ))

    return lsp.WorkspaceEdit(changes=changes)


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #

if __name__ == '__main__':
    server.start_io()
