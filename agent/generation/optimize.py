"""
DSPy optimisation runner.

Uses MIPROv2 to optimise JSGFGenerationProgram prompts against collected
(description, examples, grammar_source) training triples.

Usage:
    python agent/generation/optimize.py \
        --trainset data/trainset.jsonl \
        --output optimized_program.json \
        --workspace path/to/workspace

Requires: pip install dspy anthropic
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_HERE))


def main():
    parser = argparse.ArgumentParser(description='Optimise JSGFGenerationProgram with MIPROv2')
    parser.add_argument('--trainset', required=True, help='Path to JSONL training data')
    parser.add_argument('--output', required=True, help='Path to save optimised program')
    parser.add_argument('--workspace', required=True, help='Workspace root for grammar index')
    parser.add_argument('--num-candidates', type=int, default=10)
    parser.add_argument('--num-trials', type=int, default=30)
    args = parser.parse_args()

    try:
        import dspy
    except ImportError:
        print("Error: pip install dspy", file=sys.stderr)
        sys.exit(1)

    from core.dialect import DialectRegistry
    from core.index import GrammarIndex
    from agent.api import GrammarAgentAPI
    from agent.generation.program import JSGFGenerationProgram
    from agent.generation.metrics import JSGFCoverageMetric

    workspace = Path(args.workspace).resolve()
    dialect_cfg = workspace / 'jsgf-dialect.json'
    dialect = (
        DialectRegistry.from_config(dialect_cfg)
        if dialect_cfg.exists()
        else DialectRegistry.standard()
    )
    index = GrammarIndex(workspace, dialect)
    index.index_workspace()
    api = GrammarAgentAPI(index)

    # Load training examples
    trainset = []
    with open(args.trainset) as f:
        for line in f:
            row = json.loads(line)
            example = dspy.Example(
                intent_description=row['description'],
                examples=row['examples'],
                api=api,
                target_file=Path(row['target_file']),
                required_utterances=row['examples'],
            ).with_inputs('intent_description', 'examples')
            trainset.append(example)

    print(f"Loaded {len(trainset)} training examples")

    program = JSGFGenerationProgram()
    metric = JSGFCoverageMetric()

    teleprompter = dspy.MIPROv2(
        metric=metric,
        num_candidates=args.num_candidates,
        num_trials=args.num_trials,
        verbose=True,
    )

    optimised = teleprompter.compile(program._inner, trainset=trainset)
    optimised.save(args.output)
    print(f"Saved optimised program to {args.output}")


if __name__ == '__main__':
    main()
