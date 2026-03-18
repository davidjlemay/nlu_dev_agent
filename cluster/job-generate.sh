#!/bin/bash
#SBATCH --job-name=nlu-generate
#SBATCH --ntasks=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00

PROJ=/scratch/$USER/nlu_dev_agent
SIF=/scratch/$USER/nlu-agent.sif

# Usage: sbatch job-generate.sh <grammar_file> <intent> <examples_json>
# Example:
#   sbatch job-generate.sh grammars/intent.jsgf "transfer money" \
#     '["transfer 100 dollars", "send 50 to john"]'
GRAMMAR=${1:-grammars/intent.jsgf}
INTENT=${2:-"transfer money"}
EXAMPLES=${3:-'["transfer 100 dollars"]'}

singularity exec \
  --bind $PROJ:/app \
  --env ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --env LLM_MODEL=${LLM_MODEL:-claude-opus-4-6} \
  $SIF \
  /app/.venv/bin/python3 /app/skills/jsgf-generate/generate.py \
    $GRAMMAR \
    --intent "$INTENT" \
    --examples "$EXAMPLES" \
    --workspace /app/grammars/
