"""
JSGFGenerationProgram: 4-module DSPy pipeline for JSGF grammar generation.

Modules (in order):
1. analyze_intent    : intent + examples → slot_types, rule_structure
2. find_reusable     : slot_types + available_rules → rules_to_import, rules_to_create
3. generate_grammar  : all of the above + dialect_functions → grammar_source
4. correct_grammar   : grammar_source + diagnostics + uncovered → corrected_source

Requires `dspy` to be installed: pip install dspy
"""

from __future__ import annotations

from pathlib import Path


def _import_dspy():
    try:
        import dspy
        return dspy
    except ImportError:
        raise ImportError(
            "DSPy is not installed. Install it with: pip install dspy"
        )


class JSGFGenerationProgram:
    """
    Lazy-loaded DSPy program.  The dspy import only happens when this class
    is instantiated, so core and LSP modules don't require dspy at startup.
    """

    def __init__(self):
        dspy = _import_dspy()

        class _Inner(dspy.Module):
            def __init__(self):
                self.analyze_intent = dspy.ChainOfThought(
                    'intent_description, examples -> slot_types, rule_structure'
                )
                self.find_reusable = dspy.Predict(
                    'slot_types, available_rules -> rules_to_import, rules_to_create'
                )
                self.generate_grammar = dspy.ChainOfThought(
                    'intent_description, rule_structure, rules_to_import, '
                    'dialect_functions -> grammar_source'
                )
                self.correct_grammar = dspy.ChainOfThought(
                    'grammar_source, diagnostics, uncovered_utterances -> corrected_source'
                )

            def forward(
                self,
                intent_description: str,
                examples: list[str],
                context,  # GenerationContext
            ) -> object:  # dspy.Prediction
                analysis = self.analyze_intent(
                    intent_description=intent_description,
                    examples=str(examples),
                )
                reuse = self.find_reusable(
                    slot_types=analysis.slot_types,
                    available_rules=str([r['name'] for r in context.existing_rules]),
                )
                grammar = self.generate_grammar(
                    intent_description=intent_description,
                    rule_structure=analysis.rule_structure,
                    rules_to_import=reuse.rules_to_import,
                    dialect_functions=str([f['name'] for f in context.dialect_functions]),
                )
                return grammar

            def correct(
                self,
                grammar_source: str,
                diagnostics: list[str],
                uncovered_utterances: list[str],
            ) -> object:  # dspy.Prediction
                return self.correct_grammar(
                    grammar_source=grammar_source,
                    diagnostics=str(diagnostics),
                    uncovered_utterances=str(uncovered_utterances),
                )

        self._inner = _Inner()

    def forward(self, intent_description: str, examples: list[str], context):
        return self._inner.forward(intent_description, examples, context)

    def correct(self, grammar_source: str, diagnostics: list[str], uncovered: list[str]):
        return self._inner.correct(grammar_source, diagnostics, uncovered)

    def save(self, path: Path) -> None:
        """Persist the compiled program to *path*."""
        _import_dspy()
        self._inner.save(str(path))

    def load(self, path: Path) -> None:
        """Load a previously compiled program from *path*."""
        _import_dspy()
        self._inner.load(str(path))
