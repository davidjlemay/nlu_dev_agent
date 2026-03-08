# Quick Start Guide

Get started with the NLU Training Transcript Generator in 5 minutes.

## Prerequisites

```bash
pip install anthropic requests --break-system-packages
```

Set your API key:
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

## Test with Mock Data (No API Required)

Run the demo to see how it works:

```bash
python test_transcript_generator.py
```

This will:
1. Load sample Jira epic and commits
2. Parse requirements into subtasks
3. Map commits to subtasks  
4. Generate complete transcript
5. Save output to `example_transcript.json`

**Output:** See realistic training data without making any API calls!

## Run with Real Data

### Step 1: Download Jira + Git Data

First, collect your data using the jira downloader:

```bash
python jira_git_downloader.py \
    --project YOUR_PROJECT \
    --search "nlu" \
    --jira-url https://your-jira.atlassian.net \
    --output-dir ./jira_output
```

This creates:
```
jira_output/
  ├── epics/*.json
  ├── commits.json
  └── mr_refs.json
```

### Step 2: Prepare Instructions

Create a file with your NLU development guidelines:

```bash
cat > nlu_instructions.txt << 'EOF'
# NLU Development Instructions

## Adding Intents
1. Review existing patterns
2. Add to public intent rule
3. Define intent pattern
4. Expand and test

## Adding Canonicals
1. Check existing format
2. Add canonical values
3. Include variations
...
EOF
```

See `sample_instructions.txt` for a complete example.

### Step 3: Generate Transcripts

```bash
python transcript_generator.py \
    --input-dir ./jira_output \
    --instructions ./nlu_instructions.txt \
    --output-dir ./transcripts \
    --model claude-sonnet-4-20250514
```

### Step 4: Review Output

Check generated transcripts:

```bash
ls transcripts/
# NLU-4821_transcript.json
# NLU-4822_transcript.json
# generation_summary.json

# View one
python -m json.tool transcripts/NLU-4821_transcript.json | less
```

## Understanding the Output

Each transcript JSON contains:

```json
{
  "jira_id": "NLU-4821",
  "transcript": "# Training Transcript...\n\n### Subtask 1...",
  "subtasks": [
    {
      "id": "subtask_1",
      "type": "add_intent",
      "goal": "Add check_baggage_fee intent",
      "files": ["grammars/domain.jsgf"],
      "dependencies": []
    }
  ],
  "metadata": {
    "subtask_count": 4,
    "commit_count": 3,
    "subtask_types": ["add_intent", "add_canonicals", ...]
  }
}
```

The `transcript` field contains the formatted training data showing:
- Reasoning steps
- Tool calls (file_read, file_modify, bash, etc.)
- Observations from each action
- Error recovery when applicable

## Using for Training

### Convert to Your Training Format

Example for converting to a simple prompt/completion format:

```python
import json

with open('transcripts/NLU-4821_transcript.json') as f:
    data = json.load(f)

# Extract the full transcript
transcript = data['transcript']

# Create training example
training_example = {
    'prompt': f"Task: {data['jira_id']}\n\n{data['subtasks'][0]['goal']}",
    'completion': transcript
}
```

### For Multi-Turn Conversations

Parse the transcript into individual steps:

```python
import re

# Split transcript by subtask sections
sections = re.split(r'###\s+', transcript)

for section in sections[1:]:  # Skip header
    # Extract reasoning/action/observation blocks
    steps = re.findall(
        r'\*\*Reasoning\*\*:(.*?)\*\*Action\*\*:(.*?)\*\*Observation\*\*:(.*?)(?=\*\*Reasoning|\Z)',
        section,
        re.DOTALL
    )
    
    for reasoning, action, observation in steps:
        # Create training example for each step
        pass
```

## Customization

### Limit Number of Epics (Testing)

```bash
python transcript_generator.py \
    --input-dir ./jira_output \
    --instructions ./nlu_instructions.txt \
    --output-dir ./transcripts \
    --limit 5  # Process only first 5 epics
```

### Use Different Model

```bash
python transcript_generator.py \
    --model claude-opus-4-20250514 \  # More powerful
    ...
```

or

```bash
python transcript_generator.py \
    --model claude-haiku-4-20250308 \  # Faster, cheaper
    ...
```

## Troubleshooting

### Issue: "No such file or directory: epics"

**Solution:** Make sure you ran `jira_git_downloader.py` first and the output directory contains the expected structure.

### Issue: "ANTHROPIC_API_KEY not found"

**Solution:** 
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or pass directly in code by modifying `LLMClient` initialization.

### Issue: Transcripts are too short/generic

**Solutions:**
1. Improve your instruction file - add more detailed procedures
2. Use a more powerful model (Opus instead of Sonnet)
3. Add more commit context in your git data
4. Increase max_tokens in trajectory generation

### Issue: JSON parsing errors

**Solution:** The script includes JSON cleanup, but if you see persistent errors:
1. Check that your LLM responses don't include code fences
2. Verify system prompts enforce JSON-only output
3. Add additional cleanup in `_clean_json_response()`

## Next Steps

1. **Generate more data:** Run on all your epics
2. **Augment:** Create variants (see README section on augmentation)
3. **Validate:** Manually review a sample of transcripts
4. **Train:** Use transcripts for fine-tuning
5. **Iterate:** Improve based on agent performance

## Advanced Usage

### Custom LLM Integration

Replace the LLM client:

```python
from transcript_generator import TranscriptGenerator, LLMClient

class MyLLMClient(LLMClient):
    def generate(self, prompt, **kwargs):
        # Your API here
        return response_text

llm = MyLLMClient()
generator = TranscriptGenerator(llm, instructions, tool_schemas)
```

### Batch Processing

Process epics in parallel:

```python
from concurrent.futures import ThreadPoolExecutor
from transcript_generator import TranscriptGenerator, LLMClient

def process_epic(epic_data):
    return generator.generate_transcript_from_epic(epic_data)

with ThreadPoolExecutor(max_workers=5) as executor:
    results = executor.map(process_epic, epic_data_list)
```

### Custom Subtask Types

Add your own task types:

```python
from transcript_generator import SUBTASK_TEMPLATES

SUBTASK_TEMPLATES['my_custom_task'] = {
    'required_steps': ['step1', 'step2', 'step3'],
    'typical_errors': ['error1', 'error2'],
    'validation': 'custom_test_passes'
}
```

## Questions?

See the full README.md for detailed architecture and design decisions.
