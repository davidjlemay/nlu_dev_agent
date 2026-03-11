#!/bin/bash
#SBATCH --job-name=nlu-pi-agent
#SBATCH --ntasks=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00

PROJ=/scratch/$USER/nlu_dev_agent
SIF=/scratch/$USER/nlu-agent.sif

singularity exec \
  --bind $PROJ:/app \
  --env ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  $SIF \
  bash /app/pi.sh
