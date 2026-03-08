#!/usr/bin/env python3
"""
Test script for transcript generator with mock LLM responses.
Demonstrates the full workflow without requiring actual API calls.
"""

import json
from pathlib import Path
from transcript_generator import (
    TranscriptGenerator, LLMClient, RequirementsParser,
    CommitMapper, TrajectoryGenerator, Subtask, TOOL_SCHEMAS
)


class MockLLMClient(LLMClient):
    """Mock LLM client that returns pre-defined responses for testing."""
    
    def __init__(self):
        super().__init__()
        self.call_count = 0
    
    def generate(self, prompt: str, response_format: str = "text", **kwargs) -> str:
        """Return mock responses based on prompt content."""
        self.call_count += 1
        
        # Check if this is a requirements parsing prompt
        if "extract a list of discrete subtasks" in prompt.lower():
            return self._mock_requirements_response()
        
        # Check if this is a trajectory generation prompt
        if "reconstructing an nlu developer" in prompt.lower():
            return self._mock_trajectory_response(prompt)
        
        return "Mock LLM response"
    
    def _mock_requirements_response(self) -> str:
        """Mock response for requirements parsing."""
        return json.dumps({
            "subtasks": [
                {
                    "id": "subtask_1",
                    "type": "add_intent",
                    "goal": "Add check_baggage_fee intent pattern to grammar",
                    "files": ["grammars/flight_booking.jsgf"],
                    "dependencies": []
                },
                {
                    "id": "subtask_2",
                    "type": "add_nonterminal",
                    "goal": "Create baggage_type non-terminal",
                    "files": ["grammars/flight_booking.jsgf"],
                    "dependencies": ["subtask_1"]
                },
                {
                    "id": "subtask_3",
                    "type": "add_canonicals",
                    "goal": "Add canonical forms for baggage_type",
                    "files": ["canonicals/flight_booking_canonicals.txt"],
                    "dependencies": ["subtask_2"]
                },
                {
                    "id": "subtask_4",
                    "type": "add_unit_tests",
                    "goal": "Add 15 unit test utterances for baggage fee queries",
                    "files": ["tests/flight_booking_unit_tests.txt"],
                    "dependencies": ["subtask_3"]
                }
            ]
        })
    
    def _mock_trajectory_response(self, prompt: str) -> str:
        """Mock response for trajectory generation based on subtask type."""
        
        # Detect subtask type from prompt
        if "add_intent" in prompt or "intent pattern" in prompt.lower():
            return self._mock_add_intent_trajectory()
        elif "add_nonterminal" in prompt or "non-terminal" in prompt.lower():
            return self._mock_add_nonterminal_trajectory()
        elif "add_canonicals" in prompt or "canonical forms" in prompt.lower():
            return self._mock_add_canonicals_trajectory()
        elif "add_unit_tests" in prompt or "unit test" in prompt.lower():
            return self._mock_add_unit_tests_trajectory()
        
        return "Mock trajectory"
    
    def _mock_add_intent_trajectory(self) -> str:
        return """**Reasoning**: I need to add the check_baggage_fee intent to the flight booking grammar. First, let me check the existing structure to understand the pattern.

**Action**: file_read
```
path: domains/flight_booking/grammars/flight_booking.jsgf
```

**Observation**:
```jsgf
#JSGF V1.0;

grammar flight_booking;

public <intent> = <book_flight> | <check_flight_status> | <modify_booking> | <cancel_flight>;

<book_flight> = (book | reserve | get) [a] flight [to <destination>];
<check_flight_status> = (check | what is) [my] flight status;
...
```

**Reasoning**: I can see the pattern. I need to add check_baggage_fee to the public intent rule and define the intent pattern. Let me check if there are similar fee-related patterns in other domains.

**Action**: bash
```
command: grep -r "fee" domains/*/grammars/*.jsgf | head -5
```

**Observation**:
```
domains/hotel_booking/grammars/hotel.jsgf:<check_cancellation_fee> = (what is | how much) [the] cancellation fee;
domains/car_rental/grammars/car_rental.jsgf:<check_insurance_fee> = insurance (cost | fee | price);
```

**Reasoning**: Good, I can see the convention uses "(what is | how much)" for fee queries. Now I'll add the check_baggage_fee intent to the public rule.

**Action**: file_modify
```
path: domains/flight_booking/grammars/flight_booking.jsgf
operation: replace
old: public <intent> = <book_flight> | <check_flight_status> | <modify_booking> | <cancel_flight>;
content: public <intent> = <book_flight> | <check_flight_status> | <modify_booking> | <cancel_flight> | <check_baggage_fee>;
```

**Observation**: File modified successfully.

**Reasoning**: Now I need to add the intent definition. I'll reference a baggage_type non-terminal that will be created in the next subtask.

**Action**: file_modify
```
path: domains/flight_booking/grammars/flight_booking.jsgf
operation: insert_at_end
content: 
<check_baggage_fee> = (how much | what) (is | are) [the] <baggage_type> (baggage | luggage) [fee | fees | cost]
                     | <baggage_type> (baggage | luggage) (fee | fees | cost | price)
                     | (check | tell me) <baggage_type> (baggage | luggage) (fee | fees);
```

**Observation**: File modified successfully.

**Reasoning**: The intent pattern is added but references <baggage_type> which doesn't exist yet. Let me try to expand the grammar to see the error.

**Action**: bash
```
command: cd domains/flight_booking && ./scripts/expand_grammar.sh flight_booking.jsgf
```

**Observation**:
```
Expanding grammar flight_booking.jsgf...
ERROR: Line 45: Undefined non-terminal <baggage_type>
Expansion failed.
```

**Reasoning**: As expected, the expansion fails because baggage_type is not defined yet. This is normal - it will be added in the next subtask. The intent pattern structure is correct."""
    
    def _mock_add_nonterminal_trajectory(self) -> str:
        return """**Reasoning**: I need to add the baggage_type non-terminal definition to the grammar. This will reference canonical forms that will be added in the next subtask.

**Action**: file_read
```
path: domains/flight_booking/grammars/flight_booking.jsgf
lines: all
```

**Observation**: [File content showing existing non-terminal definitions]

**Reasoning**: I can see the pattern for defining non-terminals. They reference canonicals using @prefix. I'll add the baggage_type non-terminal.

**Action**: file_modify
```
path: domains/flight_booking/grammars/flight_booking.jsgf
operation: insert_at_end
content:
<baggage_type> = @baggage_type;
```

**Observation**: File modified successfully.

**Reasoning**: Now let me try expanding the grammar again to see if the syntax is correct.

**Action**: bash
```
command: cd domains/flight_booking && ./scripts/expand_grammar.sh flight_booking.jsgf
```

**Observation**:
```
Expanding grammar flight_booking.jsgf...
Expansion successful: 2,847 unique utterances generated
Running unit tests...
Tests passed: 142/145
Tests failed: 3

Failed tests:
1. "how much are baggage fees" -> ERROR: @baggage_type canonical not found
```

**Reasoning**: The grammar expansion works now! The syntax is correct. The test failures are expected because we haven't added the canonical forms yet. That's the next subtask."""
    
    def _mock_add_canonicals_trajectory(self) -> str:
        return """**Reasoning**: I need to add canonical forms for baggage_type. Let me first check the existing canonical file format.

**Action**: file_read
```
path: domains/flight_booking/canonicals/flight_booking_canonicals.txt
lines: 1-30
```

**Observation**:
```
# Flight class canonicals
@flight_class: economy | coach | business | first class | premium economy

# Airline canonicals
@airline: united | delta | american | southwest | jetblue

# Destination canonicals
@destination: new york | los angeles | chicago | miami
...
```

**Reasoning**: I can see the format: `@category_name: value1 | value2 | value3`. I'll add the baggage_type canonical forms following this pattern.

**Action**: file_modify
```
path: domains/flight_booking/canonicals/flight_booking_canonicals.txt
operation: insert_at_end
content:

# Baggage type canonicals
@baggage_type: checked | checked bag | carry on | carry-on | hand luggage | oversized | oversized bag | sports equipment
```

**Observation**: File modified successfully.

**Reasoning**: Now let me expand the grammar and run tests to verify the canonicals work.

**Action**: bash
```
command: cd domains/flight_booking && ./scripts/expand_grammar.sh flight_booking.jsgf
```

**Observation**:
```
Expanding grammar flight_booking.jsgf...
Expansion successful: 2,963 unique utterances generated
Running unit tests...
Tests passed: 145/145
Tests failed: 0

All tests passed!
```

**Reasoning**: Excellent! The grammar expands successfully and all existing tests pass. The canonical forms are working correctly."""
    
    def _mock_add_unit_tests_trajectory(self) -> str:
        return """**Reasoning**: I need to add unit tests for the baggage fee queries. Let me check the test file format first.

**Action**: file_read
```
path: domains/flight_booking/tests/flight_booking_unit_tests.txt
lines: 1-20
```

**Observation**:
```
# Unit tests for flight_booking domain
# Format: utterance | expected_intent | expected_slots

book a flight to new york | book_flight | destination:new_york
what is my flight status | check_flight_status | 
cancel my reservation | cancel_flight |
...
```

**Reasoning**: The format is: `utterance | intent | slots`. I need to add 15 diverse test cases covering all baggage types.

**Action**: file_modify
```
path: domains/flight_booking/tests/flight_booking_unit_tests.txt
operation: insert_at_end
content:

# Baggage fee tests - NLU-4821
how much is checked baggage | check_baggage_fee | baggage_type:checked
what are the carry on fees | check_baggage_fee | baggage_type:carry_on
checked bag cost | check_baggage_fee | baggage_type:checked
tell me oversized luggage fees | check_baggage_fee | baggage_type:oversized
how much is carry-on baggage | check_baggage_fee | baggage_type:carry_on
what is the fee for checked bags | check_baggage_fee | baggage_type:checked
carry on luggage price | check_baggage_fee | baggage_type:carry_on
check oversized bag fees | check_baggage_fee | baggage_type:oversized
what are sports equipment fees | check_baggage_fee | baggage_type:sports_equipment
how much for hand luggage | check_baggage_fee | baggage_type:hand_luggage
checked baggage fee for international | check_baggage_fee | baggage_type:checked
what is oversized luggage cost | check_baggage_fee | baggage_type:oversized
carry-on bag fees | check_baggage_fee | baggage_type:carry_on
tell me checked bag price | check_baggage_fee | baggage_type:checked
how much are baggage fees | check_baggage_fee | baggage_type:checked
```

**Observation**: File modified successfully. Added 15 test utterances.

**Reasoning**: Now let me run the unit tests to verify they all pass.

**Action**: bash
```
command: python scripts/run_unit_tests.py --domain flight_booking --filter check_baggage_fee
```

**Observation**:
```
Running unit tests for flight_booking domain...
Filtering for: check_baggage_fee

Test results:
- Total tests: 15
- Passed: 13
- Failed: 2

Failed tests:
1. "how much are baggage fees" -> predicted: check_baggage_fee (correct) | baggage_type: NONE (expected: checked)
2. "what are sports equipment fees" -> predicted: check_flight_status | expected: check_baggage_fee

Accuracy: 86.7% (13/15)
```

**Reasoning**: Two failures. The first is because generic "baggage fees" doesn't specify a type. The second suggests "sports equipment" isn't being recognized. Let me fix these issues.

**Action**: file_modify
```
path: domains/flight_booking/canonicals/flight_booking_canonicals.txt
operation: replace
old: @baggage_type: checked | checked bag | carry on | carry-on | hand luggage | oversized | oversized bag | sports equipment
content: @baggage_type: checked | checked bag | carry on | carry-on | hand luggage | oversized | oversized bag | sports equipment | sporting equipment | special item
```

**Observation**: File modified successfully.

**Reasoning**: Added variations for sports equipment. Now let me add a default value for when baggage type is not specified.

**Action**: file_modify
```
path: domains/flight_booking/grammars/flight_booking.jsgf
operation: replace
old: <baggage_type> = @baggage_type;
content: <baggage_type> = @baggage_type | {checked};
```

**Observation**: File modified successfully.

**Reasoning**: Added {checked} as the default. Now let me re-run the tests.

**Action**: bash
```
command: python scripts/run_unit_tests.py --domain flight_booking --filter check_baggage_fee
```

**Observation**:
```
Running unit tests for flight_booking domain...

Test results:
- Total tests: 15
- Passed: 15
- Failed: 0

Accuracy: 100% (15/15)
```

**Reasoning**: Perfect! All 15 unit tests now pass. The baggage fee coverage is complete and working correctly."""


def test_transcript_generation():
    """Test the transcript generation workflow with mock LLM."""
    
    print("="*80)
    print("Testing Transcript Generator with Mock LLM")
    print("="*80)
    
    # Load sample data
    sample_dir = Path('/home/claude/sample_data')
    
    with open(sample_dir / 'epics/NLU-4821.json') as f:
        epic = json.load(f)
    
    with open(sample_dir / 'commits.json') as f:
        commits = json.load(f)
    
    # Prepare epic data
    epic_data = {
        'jira_id': epic['key'],
        'requirements': epic['fields']['description'],
        'summary': epic['fields']['summary'],
        'commits': commits,
        'epic_metadata': epic
    }
    
    # Load instructions
    instructions_file = Path('/home/claude/sample_instructions.txt')
    with open(instructions_file) as f:
        generic_instructions = f.read()
    
    # Initialize with mock LLM
    mock_llm = MockLLMClient()
    
    print("\n[Test] Initializing TranscriptGenerator...")
    generator = TranscriptGenerator(
        llm_client=mock_llm,
        generic_instructions=generic_instructions,
        tool_schemas=TOOL_SCHEMAS
    )
    
    print("[Test] Generating transcript...")
    result = generator.generate_transcript_from_epic(epic_data)
    
    print("\n" + "="*80)
    print("GENERATED TRANSCRIPT")
    print("="*80)
    print(f"\nJira ID: {result['jira_id']}")
    print(f"Subtasks: {result['metadata']['subtask_count']}")
    print(f"Subtask Types: {result['metadata']['subtask_types']}")
    
    print("\n" + "-"*80)
    print("FULL TRANSCRIPT:")
    print("-"*80)
    print(result['transcript'])
    
    print("\n" + "="*80)
    print(f"LLM API Calls Made: {mock_llm.call_count}")
    print("="*80)
    
    # Save result
    output_file = Path('/home/claude/test_transcript_output.json')
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✓ Test transcript saved to: {output_file}")
    
    return result


def test_individual_components():
    """Test individual components separately."""
    
    print("\n" + "="*80)
    print("Testing Individual Components")
    print("="*80)
    
    mock_llm = MockLLMClient()
    
    # Test 1: Requirements Parser
    print("\n[Test 1] Requirements Parser")
    print("-"*40)
    
    parser = RequirementsParser(mock_llm)
    sample_requirements = """Add support for baggage fee queries.
    
Requirements:
- Add check_baggage_fee intent
- Create baggage_type non-terminal
- Add canonical forms for baggage types
- Add 15+ unit tests
"""
    
    subtasks = parser.parse_requirements_to_subtasks(
        sample_requirements,
        "Generic instructions..."
    )
    
    print(f"Extracted {len(subtasks)} subtasks:")
    for st in subtasks:
        print(f"  - {st.type}: {st.goal}")
    
    # Test 2: Commit Mapper
    print("\n[Test 2] Commit Mapper")
    print("-"*40)
    
    mapper = CommitMapper()
    
    sample_commits = [
        {
            'message': 'Add check_baggage_fee intent to grammar',
            'files': ['grammars/flight_booking.jsgf']
        },
        {
            'message': 'Add canonical forms for baggage types',
            'files': ['canonicals/flight_booking_canonicals.txt']
        }
    ]
    
    mapping = mapper.map_commits_to_subtasks(subtasks, sample_commits)
    
    print(f"Mapped commits to {len(mapping)} subtasks")
    for subtask_id, commits in mapping.items():
        print(f"  {subtask_id}: {len(commits)} commit(s)")
    
    # Test 3: Trajectory Generator
    print("\n[Test 3] Trajectory Generator")
    print("-"*40)
    
    traj_gen = TrajectoryGenerator(mock_llm, TOOL_SCHEMAS)
    
    if subtasks:
        trajectory = traj_gen.generate_subtask_trajectory(
            subtasks[0],
            [],
            "Sample instructions..."
        )
        
        print("Generated trajectory preview (first 500 chars):")
        print(trajectory[:500] + "...")
    
    print("\n" + "="*80)
    print(f"Component tests complete. Total LLM calls: {mock_llm.call_count}")
    print("="*80)


if __name__ == '__main__':
    print("\nRunning component tests...")
    test_individual_components()
    
    print("\n\n")
    
    print("Running full transcript generation test...")
    test_transcript_generation()
    
    print("\n✅ All tests completed successfully!")
