# NLU Training Transcript Generator

A system for transforming Jira epics and GitLab commits into high-quality training transcripts for fine-tuning an NLU development agent.

## Overview

This tool automates the creation of SFT (Supervised Fine-Tuning) training data by reconstructing developer workflows from:

1. **Jira Requirements** - Task descriptions and acceptance criteria
2. **Generic Instructions** - Standard NLU development procedures
3. **Git Commits** - Actual code changes and commit messages

The generated transcripts teach an AI agent to automate repetitive NLU tasks like:
- Adding intents and non-terminals to JSGF grammars
- Creating canonical forms for entity recognition
- Writing unit tests
- Modifying regex normalization rules
- Running grammar expansion and testing loops

## Architecture

### Multi-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Stage 0: Requirements → Subtasks                                │
│  • Parse Jira description                                       │
│  • Extract discrete subtasks (add_intent, add_canonicals, etc.) │
│  • Identify dependencies between subtasks                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 1: Commits → Subtasks Mapping                            │
│  • Match commits to subtasks by file overlap                    │
│  • Score matches using commit messages                          │
│  • Handle multi-file commits                                    │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 2: Trajectory Generation (per subtask)                    │
│  • Use LLM to reconstruct workflow                              │
│  • Generate: Reasoning → Action → Observation sequences         │
│  • Include JSGF expansion/testing loops                         │
│  • Add realistic error recovery cycles                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Stage 3: Combine & Finalize                                     │
│  • Merge subtask trajectories                                   │
│  • Add task summary and metadata                                │
│  • Validate tool call formats                                   │
│  • Output JSON training data                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Requirements Parser (`RequirementsParser`)

Extracts structured subtasks from Jira descriptions using LLM.

**Input:**
```
Add support for baggage fee queries:
- Add check_baggage_fee intent
- Create baggage_type non-terminal
- Add canonical forms
- Minimum 15 unit tests
```

**Output:**
```json
{
  "subtasks": [
    {
      "id": "subtask_1",
      "type": "add_intent",
      "goal": "Add check_baggage_fee intent pattern",
      "files": ["grammars/flight_booking.jsgf"],
      "dependencies": []
    },
    ...
  ]
}
```

### 2. Commit Mapper (`CommitMapper`)

Maps git commits to subtasks based on:
- File overlap (weight: 2 per file)
- Commit message keyword matching (weight: 1)

**Subtask Type Patterns:**
- `add_intent`: "add.*intent", "new intent", "intent.*pattern"
- `add_canonicals`: "canonical", "canonical.*form", "add.*values"
- `add_unit_tests`: "test", "unit test", "test.*utterance"
- `modify_regex`: "regex", "normalization", "pattern.*fix"

### 3. Trajectory Generator (`TrajectoryGenerator`)

Uses LLM to reconstruct developer workflow with proper tool usage.

**Subtask Templates** guide generation with:
- Required workflow steps
- Common error patterns
- Validation methods

**Example trajectory step:**
```markdown
**Reasoning**: I need to check existing patterns before adding new intent.

**Action**: file_read
```
path: domains/flight_booking/grammars/flight_booking.jsgf
```

**Observation**:
```jsgf
#JSGF V1.0;
grammar flight_booking;
public <intent> = <book_flight> | <check_flight_status>;
...
```
```

### 4. Tool Schemas

Defines available tools for the agent:

- **bash**: Execute shell commands
- **file_read**: Read file contents
- **file_modify**: Edit existing files (insert, replace, delete)
- **file_create**: Create new files

## Usage

### Basic Usage

```bash
python transcript_generator.py \
    --input-dir ./jira_output \
    --instructions ./nlu_instructions.txt \
    --output-dir ./transcripts \
    --model claude-sonnet-4-20250514
```

### Input Data Structure

Expected from `jira_git_downloader.py`:

```
input-dir/
  ├── epics/
  │   ├── NLU-4821.json
  │   └── NLU-4822.json
  ├── commits.json
  ├── mr_refs.json
  └── merge_requests.json
```

### Output Structure

```
output-dir/
  ├── NLU-4821_transcript.json
  ├── NLU-4822_transcript.json
  └── generation_summary.json
```

### Testing with Mock Data

```bash
# Run with mock LLM (no API calls)
python test_transcript_generator.py
```

This demonstrates the full pipeline using pre-defined responses.

## Key Design Decisions

### 1. Why Subtask Decomposition?

**Benefits:**
- Maps generic instructions to specific requirements
- Enables modular trajectory generation
- Allows dependency tracking between tasks
- Improves LLM prompt focus

**Alternative considered:** Generate entire trajectory in one shot
**Rejected because:** Too complex for consistent quality, loses granular control

### 2. Why Separate Requirements Parsing?

**Benefits:**
- Structured subtasks improve commit mapping accuracy
- Enables requirement → instruction mapping
- Provides clear task boundaries
- Supports dependency-aware ordering

**Alternative considered:** Parse requirements within trajectory generation
**Rejected because:** Less reusable, harder to validate, coupling issues

### 3. Why Include Error Recovery?

**Benefits:**
- More realistic training data
- Teaches debugging patterns
- Shows proper iteration loops
- Valuable for agent robustness

**Implementation:**
- Use subtask templates to define common errors
- Detect "fix" patterns in commit messages
- Generate 1-2 error cycles per subtask when appropriate

### 4. Why Exclude E2E Testing (for now)?

**Rationale:**
- Signal too sparse in current data
- Unit testing already validates implementation
- E2E reserved for future bug-fixing iteration
- Keeps transcript scope manageable

**Future:** Bug tickets will include E2E evaluation and accuracy improvement cycles

## Prompt Engineering

### Requirements Parsing Prompt

Key elements:
- Explicit JSON schema with examples
- Subtask type vocabulary (add_intent, add_canonicals, etc.)
- Dependency identification instructions
- File path inference from task type

### Trajectory Generation Prompt

Key elements:
- Subtask goal and type
- Relevant instruction sections
- Commit diffs for ground truth
- Tool schemas with exact formats
- JSGF expansion/testing loop guidance
- Required workflow steps from template
- Common error patterns to potentially include

### Response Format Enforcement

For JSON responses:
```python
system_prompt = "You must respond with valid JSON only. No markdown, no preamble."
```

Then strip markdown fences:
```python
response = re.sub(r'^```json\s*', '', response)
response = re.sub(r'\s*```$', '', response)
```

## Validation & Quality Checks

### Transcript Validation

1. **Tool call syntax**: All tool calls must parse correctly
2. **File consistency**: Files read/written must exist in commits
3. **Temporal logic**: Can't edit before reading (usually)
4. **Test outcomes**: If commit mentions "fixed", show initial failure
5. **Instruction adherence**: Steps reference instruction sections

### Commit Mapping Validation

1. **Coverage**: Each subtask has ≥0 commits mapped
2. **Relevance**: File overlap or message match for each mapping
3. **No duplicates**: Same commit doesn't map to unrelated subtasks

## Extending the System

### Adding New Subtask Types

1. Add type to `SUBTASK_TEMPLATES`:

```python
SUBTASK_TEMPLATES['new_task_type'] = {
    'required_steps': [...],
    'typical_errors': [...],
    'validation': 'test_passes'
}
```

2. Add keyword patterns to `CommitMapper.SUBTASK_PATTERNS`

3. Optionally: Create specialized trajectory generator method

### Supporting New Tools

1. Add tool schema to `TOOL_SCHEMAS`:

```python
TOOL_SCHEMAS['new_tool'] = {
    "description": "What the tool does",
    "parameters": {
        "param1": "description",
        ...
    }
}
```

2. Tool will be available in prompts automatically

### Customizing LLM

Replace `LLMClient` methods:

```python
class CustomLLMClient(LLMClient):
    def generate(self, prompt, **kwargs):
        # Your LLM API integration
        pass
```

## Data Augmentation Strategies

To increase training data from limited epics:

### 1. Error Path Variants
- Same task, different initial mistakes
- Vary which test fails first
- Different recovery strategies

### 2. Exploration Order Variants
- Read files in different sequences
- Different examples examined
- Varied tool usage patterns

### 3. Style Variants
- Verbose vs terse reasoning
- Different intermediate validation approaches
- Batch vs incremental testing

Generate 3-5x data per epic without actual duplication.

## Performance Notes

### LLM API Calls Per Epic

Approximate calls needed:
- 1 call for requirements parsing
- N calls for trajectory generation (N = number of subtasks)
- Typical: 4-6 calls per epic

### Generation Time

With Anthropic API (Claude Sonnet 4):
- ~2-5 seconds per subtask trajectory
- ~10-30 seconds per complete epic
- Can process 10-20 epics in 5-10 minutes

### Cost Estimation

Claude Sonnet 4 pricing:
- Input: $3 per million tokens
- Output: $15 per million tokens

Per epic (rough estimate):
- Input: ~5K tokens (requirements + instructions + commits)
- Output: ~3K tokens (trajectory)
- Cost: ~$0.05-0.10 per epic

## Troubleshooting

### "Undefined non-terminal" errors in mock trajectories

**Expected behavior** - Mock LLM shows realistic errors that would occur during development. These demonstrate error recovery patterns for training.

### Commit mapping returns empty results

**Check:**
1. Commit data includes `message` and `files` fields
2. Message contains relevant keywords
3. Subtask files match commit changed files

### LLM generates invalid JSON

**Solutions:**
1. Add explicit format enforcement in system prompt
2. Provide few-shot examples in prompt
3. Use JSON cleanup with regex
4. Retry with format correction in follow-up prompt

### Trajectories are too generic

**Solutions:**
1. Include more commit diff context
2. Add domain-specific examples to prompt
3. Reference specific instruction sections
4. Increase temperature for variation

## Future Enhancements

### Phase 2: Bug Fixing Training

- Use bug tickets instead of feature epics
- Include evaluation results before/after
- Add E2E testing trajectories
- Show accuracy improvement cycles

### Phase 3: Multi-Epic Patterns

- Detect common patterns across epics
- Create meta-templates for frequent workflows
- Generate synthetic variations from templates

### Phase 4: Active Learning

- Deploy agent in sandbox
- Collect successful/failed attempts
- Generate new training data from deployment
- Continuous improvement loop

## License

[Your license here]

## Contributors

[Your team]

## References

- JSGF Specification: https://www.w3.org/TR/jsgf/
- SFT Training: [Your papers/resources]
- Git Commit Analysis: [Resources on mining software repositories]
