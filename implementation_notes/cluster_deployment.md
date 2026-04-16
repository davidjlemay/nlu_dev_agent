 Plan: Cluster Deployment via Singularity

 Context

 The cluster has no Node.js. The pi coding agent requires Node ≥20 (runs pi-mono/packages/coding-agent/dist/cli.js). The NLU generation loop is pure Python. The pi agent invokes Python skills as subprocesses
  via pi.exec(python, [...args]) — meaning both runtimes must share the same filesystem and executable paths within the same execution environment.

 Recommendation: Single Docker image → Single SIF

 Build one Docker image locally containing both Node.js 20 and Python 3.12. Convert to SIF locally and push to cluster.

 Why single image (not two)

 - The pi agent calls skills/*.py as subprocesses using a hardcoded .venv/bin/python3 path
 - Splitting into two SIFs would require cross-container subprocess calls (complex, fragile)
 - Node SIF + system Python would require the cluster to have Python 3.12 + all packages installed externally
 - One image is simpler to reason about and mirrors the local dev setup exactly

 The "two processes" question

 This is naturally handled: within a single SLURM job (or interactive session), the pi coding agent runs as one process and spawns Python skill subprocesses on demand. If you want the NLU generation loop
 (skills/jsgf-generate/generate.py) to run independently as a batch job, that's a separate invocation using the same SIF but with a different entrypoint — no inter-process communication needed, both just
 work on the filesystem.

 Implementation

 1. Singularity definition file (nlu-agent.def)

 Skips Docker entirely — bootstraps directly from DockerHub node:20.

 Bootstrap: docker
 From: node:20-bookworm-slim

 %post
     apt-get update && apt-get install -y --no-install-recommends \
         python3 python3-venv python3-dev python3-pip \
         git \
     && rm -rf /var/lib/apt/lists/*

     # Create app dir — project will be bind-mounted at runtime
     mkdir -p /app

 %environment
     export PYTHONDONTWRITEBYTECODE=1
     export PATH=/app/.venv/bin:$PATH

 %runscript
     exec bash /app/pi.sh "$@"

 Note: The Python venv and project files are NOT baked in — they're bind-mounted from NFS at runtime. This keeps the SIF small and lets you update grammars/code without rebuilding.

 The venv needs to be built once on the cluster. Run the setup helper from an interactive job:
     bash $PROJ/cluster/setup-venv.sh

 This script uses `singularity exec --bind $PROJ:/app` so the venv lands at
 $PROJ/.venv on the host filesystem.

 2. Build the SIF locally (three options, pick one)

 Option A — Local Singularity with sudo (cleanest, no Docker needed)
 sudo singularity build nlu-agent.sif nlu-agent.def

 Option B — Remote build on Sylabs Cloud (no sudo, no Docker, free account)
 singularity build --remote nlu-agent.sif nlu-agent.def
 # Requires: singularity remote login  (one-time setup with free sylabs.io account)

 Option C — Docker intermediary (if Docker is already running)
 docker build -t nlu-agent:latest -f Dockerfile .
 singularity build nlu-agent.sif docker-daemon://nlu-agent:latest

 Recommendation: Option A if you have sudo locally. Option B if not.

 3. Transfer and run

 # Transfer SIF
 scp nlu-agent.sif cluster:/scratch/$USER/

 # Copy project (if not already there via git)
 rsync -av --exclude='.venv' --exclude='pi-mono/node_modules' \
   ~/nlu_dev_agent/ cluster:/scratch/$USER/nlu_dev_agent/

 3. SLURM job script (interactive pi agent)

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

 4. SLURM job for standalone NLU generation (batch)

 singularity exec \
   --bind $PROJ:/app \
   --env ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
   --env LLM_MODEL=claude-opus-4-6 \
   $SIF \
   /app/.venv/bin/python3 /app/skills/jsgf-generate/generate.py \
     grammars/intent.jsgf \
     --intent "transfer money" \
     --examples '["transfer 100 dollars", "send 50 to john"]' \
     --workspace /app/grammars/

 Installing on Ubuntu 24 WSL2

 Docker (from Docker's official apt repo)

 # Add Docker's apt repo
 sudo apt-get update
 sudo apt-get install -y ca-certificates curl
 sudo install -m 0755 -d /etc/apt/keyrings
 sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
 echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] \
   https://download.docker.com/linux/ubuntu noble stable" | \
   sudo tee /etc/apt/sources.list.d/docker.list
 sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io

 # WSL2: start daemon (systemd may not auto-start it)
 sudo service docker start
 sudo usermod -aG docker $USER  # avoid needing sudo for docker commands

 Singularity (Ubuntu universe repo — simplest, no build required)

 sudo apt-get install -y singularity-container   # installs 4.1.1 from Ubuntu noble universe

 Or use Apptainer via official PPA (more up-to-date):
 sudo add-apt-repository -y ppa:apptainer/ppa
 sudo apt-get update && sudo apt-get install -y apptainer
 Both produce standard SIFs compatible with Singularity 3.8.3 on the cluster.

 Critical: avoid OCI-SIF format

 When building, do not use --oci flag — OCI-SIF is not readable by Singularity 3.8.3.
 Standard singularity build (no flags) produces a traditional SIF that works on 3.x.

 Files to create

 ┌─────────────────────────┬───────────────────────────────────────────────┐
 │          File           │                    Purpose                    │
 ├─────────────────────────┼───────────────────────────────────────────────┤
 │ Dockerfile              │ Single-image build with Node 20 + Python 3.12 │
 ├─────────────────────────┼───────────────────────────────────────────────┤
 │ cluster/job-agent.sh    │ SLURM job for interactive pi agent            │
 ├─────────────────────────┼───────────────────────────────────────────────┤
 │ cluster/job-generate.sh │ SLURM job for batch NLU generation            │
 └─────────────────────────┴───────────────────────────────────────────────┘

 Verification

 1. docker build -t nlu-agent:latest . — should succeed
 2. docker run --rm nlu-agent:latest node --version → v20.x
 3. docker run --rm nlu-agent:latest .venv/bin/python3 -c "import pyjsgf; print('ok')" → ok
 4. docker run --rm -e ANTHROPIC_API_KEY=... nlu-agent:latest python3 skills/jsgf-validate/validate.py grammars/test.jsgf --workspace grammars/ → JSON output
 5. Convert to SIF and repeat tests with singularity exec

 Confirmed constraints

 - LLM access: Full internet — Anthropic/OpenAI API calls work directly from compute nodes
 - Run mode: Both — interactive TTY sessions for pi agent + batch SLURM jobs for generation loop
 - Workspace: Shared NFS/scratch — bind-mount at runtime, do NOT bake grammars into the image

 TTY note for interactive pi agent

 The pi agent TUI requires a terminal. On the cluster:
 # Request an interactive job with a TTY
 srun --pty --ntasks=1 --mem=8G --time=02:00:00 bash

 # Then inside the interactive session:
 singularity exec \
   --bind /scratch/$USER/grammars:/app/grammars \
   --env ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
   /scratch/$USER/nlu-agent.sif \
   bash /app/pi.sh

 Or wrap in an salloc + singularity shell workflow if preferred.

 .dockerignore to keep image small

 .venv/
 __pycache__/
 *.pyc
 .git/
 pi-mono/.git/
 pi-mono/node_modules/  # only if rebuilding inside image
 *.sif
 *.zip
 nvim-linux-x86_64.tar.gz
