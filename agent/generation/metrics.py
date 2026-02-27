"""
JSGFCoverageMetric: DSPy-compatible metric for grammar generation quality.

Score = 0.4 * structural_valid + 0.6 * coverage_ratio

Structural validity is binary (1.0 if no diagnostics, 0.0 otherwise).
Coverage ratio is the fraction of required_utterances matched by the grammar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.api import GrammarAgentAPI


@dataclass
class MetricWeights:
    structural: float = 0.4
    coverage: float = 0.6


class JSGFCoverageMetric:
    """
    DSPy metric callable.

    Expected example fields:
        example.api              : GrammarAgentAPI
        example.target_file      : Path
        example.required_utterances : list[str]

    Expected prediction fields:
        prediction.grammar_source : str
    """

    def __init__(self, weights: MetricWeights | None = None):
        self.weights = weights or MetricWeights()

    def __call__(self, example, prediction, trace=None) -> float:
        api: GrammarAgentAPI = example.api
        target_file: Path = example.target_file
        required: list[str] = example.required_utterances
        grammar_source: str = prediction.grammar_source

        diags, coverage = api.validate_generated_grammar(
            grammar_source, target_file, required
        )

        structural = 1.0 if not diags else 0.0
        cov_score = coverage.coverage_ratio if coverage is not None else 0.0

        return self.weights.structural * structural + self.weights.coverage * cov_score
