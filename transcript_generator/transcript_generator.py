#!/usr/bin/env python3
"""
NLU Training Transcript Generator

Transforms Jira epics with associated GitLab commits into SFT training transcripts
for an NLU development agent. The agent learns to automate repetitive tasks like:
- Adding coverage for non-terminals
- Updating canonical forms
- Adding new rules to JSGFs
- Adding regex rules for data normalization
- Writing unit tests

The script uses an LLM to reconstruct the developer's workflow from:
1. Jira requirements
2. Generic NLU development instructions
3. Git commit diffs

Output: JSON-formatted training transcripts with tool calls, reasoning, and observations.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict


# ─────────────────────────────────────────────────────────────────────────────
# ADF / requirements helpers
# ─────────────────────────────────────────────────────────────────────────────

def _adf_to_text(node) -> str:
    """Walk an Atlassian Document Format tree and extract plain text."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    parts = []
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
    for child in node.get("content", []):
        parts.append(_adf_to_text(child))
    return " ".join(p for p in parts if p)


def _extract_requirements(field_value) -> str:
    """Extract plain text from a Jira customfield (string or ADF dict)."""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, dict):
        return _adf_to_text(field_value)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Subtask:
    """Represents a discrete subtask extracted from requirements."""
    id: str
    type: str  # add_intent, add_nonterminal, add_canonicals, add_unit_tests, modify_regex, etc.
    goal: str
    files: List[str]
    dependencies: List[str]
    
    def to_dict(self):
        return asdict(self)


@dataclass
class ToolCall:
    """Represents a single tool invocation."""
    tool: str  # bash, file_read, file_modify, file_create, etc.
    parameters: Dict[str, Any]
    
    def to_dict(self):
        return asdict(self)


@dataclass
class TrajectoryStep:
    """Single step in a trajectory: reasoning → action → observation."""
    reasoning: str
    action: ToolCall
    observation: str
    
    def to_dict(self):
        return {
            'reasoning': self.reasoning,
            'action': self.action.to_dict(),
            'observation': self.observation
        }


# ─────────────────────────────────────────────────────────────────────────────
# Subtask Templates
# ─────────────────────────────────────────────────────────────────────────────

SUBTASK_TEMPLATES = {
    'add_intent': {
        'required_steps': [
            'read_existing_patterns',
            'modify_grammar_file',
            'expand_and_test',
            'iterate_on_failures'
        ],
        'typical_errors': [
            'undefined_nonterminal',
            'syntax_error',
            'insufficient_coverage'
        ],
        'validation': 'expansion_success'
    },
    
    'add_nonterminal': {
        'required_steps': [
            'read_grammar_structure',
            'add_nonterminal_definition',
            'expand_and_test'
        ],
        'typical_errors': [
            'syntax_error',
            'missing_canonical_reference'
        ],
        'validation': 'expansion_success'
    },
    
    'add_canonicals': {
        'required_steps': [
            'read_existing_canonicals',
            'identify_format',
            'add_canonical_values',
            'expand_and_test'
        ],
        'typical_errors': [
            'format_mismatch',
            'missing_variants'
        ],
        'validation': 'unit_tests_pass'
    },
    
    'modify_regex': {
        'required_steps': [
            'read_normalization_rules',
            'identify_pattern_location',
            'modify_regex',
            'test_regex_patterns',
            'expand_and_validate'
        ],
        'typical_errors': [
            'unescaped_special_chars',
            'overly_broad_pattern',
            'regex_syntax_error'
        ],
        'validation': 'normalization_tests_pass'
    },
    
    'add_unit_tests': {
        'required_steps': [
            'read_test_format',
            'generate_test_utterances',
            'run_tests',
            'analyze_failures',
            'add_more_tests'
        ],
        'typical_errors': [
            'wrong_format',
            'insufficient_coverage',
            'incorrect_expected_slots'
        ],
        'validation': 'test_count_meets_requirement'
    },
    
    'modify_grammar': {
        'required_steps': [
            'read_grammar_rules',
            'identify_modification_point',
            'update_rules',
            'expand_and_test'
        ],
        'typical_errors': [
            'syntax_error',
            'breaking_existing_patterns'
        ],
        'validation': 'expansion_success'
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# LLM Client Abstraction
# ─────────────────────────────────────────────────────────────────────────────

class LLMClient:
    """LLM client supporting local HuggingFace models and Anthropic API."""
    
    def __init__(self, model: str = "codellama/CodeLlama-13b-Instruct-hf", 
                 api_key: Optional[str] = None,
                 device: str = "auto",
                 load_in_8bit: bool = False,
                 load_in_4bit: bool = False):
        """
        Initialize LLM client.
        
        Args:
            model: Model name or path (HuggingFace model or "claude-*" for API)
            api_key: Optional API key for Anthropic models
            device: Device placement ("auto", "cuda", "cpu")
            load_in_8bit: Load model in 8-bit quantization
            load_in_4bit: Load model in 4-bit quantization (QLoRA)
        """
        self.model_name = model
        self.api_key = api_key
        self.device = device
        self.load_in_8bit = load_in_8bit
        self.load_in_4bit = load_in_4bit
        
        # Determine if using local model or API
        self.is_local = not model.startswith("claude-")
        
        if self.is_local:
            self._load_local_model()
        else:
            self.model = None
            self.tokenizer = None
    
    def _load_local_model(self):
        """Load a local HuggingFace model."""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            
            print(f"[LLM] Loading local model: {self.model_name}")
            
            # Configure quantization if requested
            quantization_config = None
            if self.load_in_4bit:
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                )
                print("[LLM] Using 4-bit quantization (NF4)")
            elif self.load_in_8bit:
                quantization_config = BitsAndBytesConfig(load_in_8bit=True)
                print("[LLM] Using 8-bit quantization")
            
            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=True,
                padding_side="left"
            )
            
            # Set pad token if not set
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # Load model
            load_kwargs = {
                "trust_remote_code": True,
                "device_map": self.device,
            }
            
            if quantization_config:
                load_kwargs["quantization_config"] = quantization_config
            else:
                load_kwargs["torch_dtype"] = torch.bfloat16
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                **load_kwargs
            )
            
            self.model.eval()
            print(f"[LLM] Model loaded successfully on {self.device}")
            
        except ImportError as e:
            raise ImportError(
                f"Failed to import required libraries: {e}\n"
                "Install with: pip install transformers torch accelerate bitsandbytes"
            )
    
    def generate(self, prompt: str, response_format: str = "text", 
                max_tokens: int = 4000, temperature: float = 0.7,
                top_p: float = 0.95, **kwargs) -> str:
        """
        Generate content from the LLM.
        
        Args:
            prompt: The prompt to send
            response_format: "text" or "json"
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            **kwargs: Additional generation parameters
            
        Returns:
            Generated text or JSON string
        """
        if self.is_local:
            return self._generate_local(
                prompt, response_format, max_tokens, temperature, top_p, **kwargs
            )
        else:
            return self._generate_anthropic(
                prompt, response_format, max_tokens, **kwargs
            )
    
    def _generate_local(self, prompt: str, response_format: str = "text",
                       max_tokens: int = 4000, temperature: float = 0.7,
                       top_p: float = 0.95, **kwargs) -> str:
        """Generate using local HuggingFace model."""
        import torch
        
        # Format prompt based on model type
        formatted_prompt = self._format_prompt(prompt, response_format)
        
        # Tokenize
        inputs = self.tokenizer(
            formatted_prompt,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=kwargs.get('max_input_length', 8192)
        ).to(self.model.device)
        
        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
                **kwargs
            )
        
        # Decode
        generated_text = self.tokenizer.decode(
            outputs[0][inputs['input_ids'].shape[1]:],
            skip_special_tokens=True
        )
        
        return generated_text.strip()
    
    def _format_prompt(self, prompt: str, response_format: str) -> str:
        """
        Format prompt for specific model architectures.
        
        Handles different instruction formats (CodeLlama, Qwen, DeepSeek, etc.)
        """
        # Detect model family
        model_lower = self.model_name.lower()
        
        # Add JSON instruction if needed
        if response_format == "json":
            json_instruction = "\n\nIMPORTANT: You must respond with valid JSON only. No markdown code fences (no ```json), no preamble, no explanation - just the raw JSON object starting with { and ending with }."
            prompt = prompt + json_instruction
        
        # CodeLlama format
        if "codellama" in model_lower:
            # CodeLlama works best with explicit system message for structured tasks
            if response_format == "json":
                system_msg = "You are a helpful coding assistant that outputs valid JSON."
                return f"<s>[INST] <<SYS>>\n{system_msg}\n<</SYS>>\n\n{prompt} [/INST]"
            else:
                return f"<s>[INST] {prompt} [/INST]"
        
        # Llama-3.1 format
        elif "llama-3" in model_lower or "llama3" in model_lower:
            system_msg = "You are a helpful AI assistant."
            if response_format == "json":
                system_msg = "You are a helpful AI assistant that outputs valid JSON."
            return f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_msg}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        
        # Mistral/Mixtral format
        elif "mistral" in model_lower or "mixtral" in model_lower:
            return f"<s>[INST] {prompt} [/INST]"
        
        # StarCoder2 format (instruct variant)
        elif "starcoder2" in model_lower and "instruct" in model_lower:
            return f"### Instruction\n{prompt}\n\n### Response\n"
        
        # StarCoder format (base)
        elif "starcoder" in model_lower:
            return f"<fim_prefix>{prompt}<fim_suffix><fim_middle>"
        
        # Qwen format
        elif "qwen" in model_lower:
            return f"<|im_start|>system\nYou are a helpful AI assistant.<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        # DeepSeek format
        elif "deepseek" in model_lower:
            return f"<｜begin▁of▁sentence｜>User: {prompt}\n\nAssistant:"
        
        # Default: just return the prompt
        else:
            return prompt
    
    def _generate_anthropic(self, prompt: str, response_format: str = "text", 
                           max_tokens: int = 4000, **kwargs) -> str:
        """Generate using Anthropic API."""
        import os
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "Anthropic library not installed. Install with: pip install anthropic"
            )
        
        client = Anthropic(api_key=self.api_key or os.getenv("ANTHROPIC_API_KEY"))
        
        system_prompt = ""
        if response_format == "json":
            system_prompt = "You must respond with valid JSON only. No markdown, no preamble, just JSON."
        
        message = client.messages.create(
            model=self.model_name,
            max_tokens=max_tokens,
            system=system_prompt if system_prompt else None,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return message.content[0].text


# ─────────────────────────────────────────────────────────────────────────────
# Requirements Parser
# ─────────────────────────────────────────────────────────────────────────────

class RequirementsParser:
    """Extracts structured subtasks from Jira requirements."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
    
    def parse_requirements_to_subtasks(self, requirements: str, 
                                      generic_instructions: str) -> List[Subtask]:
        """
        Parse Jira requirements into discrete subtasks.
        
        Args:
            requirements: The Jira epic/issue description
            generic_instructions: Standard NLU development instructions
            
        Returns:
            List of Subtask objects
        """
        prompt = self._build_requirements_prompt(requirements, generic_instructions)
        
        try:
            response = self.llm.generate(prompt, response_format="json")
            data = json.loads(self._clean_json_response(response))
            
            subtasks = []
            for idx, st in enumerate(data.get('subtasks', [])):
                subtasks.append(Subtask(
                    id=st.get('id', f'subtask_{idx+1}'),
                    type=st.get('type', 'unknown'),
                    goal=st.get('goal', ''),
                    files=st.get('files', []),
                    dependencies=st.get('dependencies', [])
                ))
            
            return subtasks
            
        except json.JSONDecodeError as e:
            print(f"Error parsing LLM response as JSON: {e}")
            return []
    
    def _build_requirements_prompt(self, requirements: str, 
                                   generic_instructions: str) -> str:
        """Build the prompt for requirements parsing."""
        return f"""Given these Jira requirements and generic NLU development instructions,
extract a list of discrete subtasks.

REQUIREMENTS:
{requirements}

GENERIC INSTRUCTIONS (for context):
{generic_instructions[:2000]}...  

For each subtask, identify:
1. Subtask type from: add_intent, add_nonterminal, add_canonicals, add_unit_tests, modify_regex, modify_grammar
2. Specific goal (what needs to be accomplished)
3. Affected files (e.g., "grammars/domain.jsgf", "canonicals/domain_canonicals.txt")
4. Dependencies on other subtasks (by subtask ID)

Output ONLY valid JSON with this structure (no markdown, no preamble):
{{
  "subtasks": [
    {{
      "id": "subtask_1",
      "type": "add_intent",
      "goal": "Add check_baggage_fee intent pattern to grammar",
      "files": ["grammars/flight_booking.jsgf"],
      "dependencies": []
    }},
    {{
      "id": "subtask_2", 
      "type": "add_nonterminal",
      "goal": "Create baggage_type non-terminal",
      "files": ["grammars/flight_booking.jsgf"],
      "dependencies": ["subtask_1"]
    }}
  ]
}}"""
    
    @staticmethod
    def _clean_json_response(response: str) -> str:
        """Remove markdown code fences and clean JSON response."""
        # Remove ```json and ``` markers
        response = re.sub(r'^```json\s*', '', response, flags=re.MULTILINE)
        response = re.sub(r'\s*```$', '', response, flags=re.MULTILINE)
        return response.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Commit Mapper
# ─────────────────────────────────────────────────────────────────────────────

class CommitMapper:
    """Maps git commits to subtasks based on files changed and commit messages."""
    
    # Keyword patterns for subtask types
    SUBTASK_PATTERNS = {
        'add_intent': [r'add.*intent', r'new intent', r'intent.*pattern'],
        'add_nonterminal': [r'non-terminal', r'nonterminal', r'add.*slot', r'new.*slot'],
        'add_canonicals': [r'canonical', r'canonical.*form', r'add.*values'],
        'add_unit_tests': [r'test', r'unit test', r'test.*utterance'],
        'modify_regex': [r'regex', r'normalization', r'pattern.*fix'],
        'modify_grammar': [r'grammar', r'jsgf', r'rule.*update']
    }
    
    def map_commits_to_subtasks(self, subtasks: List[Subtask], 
                                commits: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Match commits to subtasks based on files and messages.
        
        Returns:
            Dict mapping subtask_id -> list of matching commits with scores
        """
        mapping = {}
        
        for subtask in subtasks:
            matching_commits = []
            
            for commit in commits:
                score = self._score_commit_for_subtask(commit, subtask)
                
                if score > 0:
                    matching_commits.append({
                        'commit': commit,
                        'score': score,
                        'matched_files': self._get_file_overlap(commit, subtask)
                    })
            
            # Sort by score and take top matches
            matching_commits.sort(key=lambda x: x['score'], reverse=True)
            mapping[subtask.id] = matching_commits[:2]  # Top 2 commits max
        
        return mapping
    
    def _score_commit_for_subtask(self, commit: Dict, subtask: Subtask) -> int:
        """Score how well a commit matches a subtask."""
        score = 0
        
        # File overlap (weight: 2 per file)
        file_overlap = self._get_file_overlap(commit, subtask)
        score += len(file_overlap) * 2
        
        # Commit message keyword matching (weight: 1)
        if self._match_commit_message(commit.get('message', ''), subtask.type):
            score += 1
        
        return score
    
    def _get_file_overlap(self, commit: Dict, subtask: Subtask) -> set:
        """Get files that appear in both commit and subtask."""
        # Note: In real data, we'd need to fetch the actual changed files
        # For now, we'll infer from commit message or need to enhance data structure
        return set()  # Placeholder
    
    def _match_commit_message(self, message: str, subtask_type: str) -> bool:
        """Check if commit message matches subtask type patterns."""
        patterns = self.SUBTASK_PATTERNS.get(subtask_type, [])
        
        for pattern in patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return True
        
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Diff formatting helper
# ─────────────────────────────────────────────────────────────────────────────

def _format_diff_files(diff_files: List[Dict], max_chars: int = 2000) -> str:
    """Render diff_files list as a readable +/- summary for LLM prompts."""
    if not diff_files:
        return ""

    parts = []
    for df in diff_files:
        if "note" in df:
            parts.append(f"  {df['note']}")
            continue

        path = df.get("new_path") or df.get("old_path") or "unknown"
        diff_str = df.get("diff", "")
        content_lines = [
            l for l in diff_str.splitlines()
            if (l.startswith('+') and not l.startswith('+++'))
            or (l.startswith('-') and not l.startswith('---'))
        ]
        added   = sum(1 for l in content_lines if l.startswith('+'))
        removed = sum(1 for l in content_lines if l.startswith('-'))

        file_lines = [f"  {path} (+{added} / -{removed}):"]
        file_lines.extend(f"  {l}" for l in content_lines)
        parts.append("\n".join(file_lines))

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n  [... truncated ...]"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Trajectory Generator
# ─────────────────────────────────────────────────────────────────────────────

class TrajectoryGenerator:
    """Generates workflow trajectories for subtasks using LLM."""

    def __init__(self, llm_client: LLMClient, tool_schemas: Dict,
                 max_tokens: int = 4000, temperature: float = 0.7,
                 no_critic: bool = False, max_critic_iterations: int = 2):
        self.llm = llm_client
        self.tools = tool_schemas
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.no_critic = no_critic
        self.max_critic_iterations = max_critic_iterations

    def generate_subtask_trajectory(self, subtask: Subtask,
                                    commits: List[Dict],
                                    instructions: str) -> str:
        """
        Generate a step-by-step trajectory for a subtask.

        When critic is enabled, runs an actor/critic loop (up to
        max_critic_iterations) before returning the final trajectory.

        Returns:
            Markdown-formatted trajectory with reasoning, actions, and observations
        """
        template = SUBTASK_TEMPLATES.get(subtask.type, {})
        actor_prompt = self._build_trajectory_prompt(subtask, commits, instructions, template)

        trajectory = self.llm.generate(
            actor_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        if self.no_critic:
            return trajectory

        # Actor / critic refinement loop
        all_diff_files = self._collect_diff_files(commits)
        for iteration in range(self.max_critic_iterations):
            critic_prompt = self._build_critic_prompt(subtask, trajectory, all_diff_files)
            critic_raw = self.llm.generate(
                critic_prompt,
                response_format="json",
                max_tokens=1000,
                temperature=0.3,
            )
            try:
                feedback = json.loads(RequirementsParser._clean_json_response(critic_raw))
            except json.JSONDecodeError:
                print(f"  [critic] iter {iteration + 1}: failed to parse response — keeping trajectory")
                break

            if feedback.get("approved"):
                print(f"  [critic] approved on iteration {iteration + 1}")
                break

            issue_summary = str(feedback.get("feedback", ""))[:120]
            print(f"  [critic] iter {iteration + 1}: revising — {issue_summary}")

            revision_prompt = self._build_revision_prompt(
                actor_prompt, trajectory, feedback.get("feedback", "")
            )
            trajectory = self.llm.generate(
                revision_prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

        return trajectory

    # ── prompt builders ──────────────────────────────────────────────────────

    def _build_trajectory_prompt(self, subtask: Subtask, commits: List[Dict],
                                  instructions: str, template: Dict) -> str:
        """Build the actor prompt for trajectory generation."""
        commit_context = self._format_commits(commits)

        jsgf_guidance = ""
        if subtask.type in ['add_intent', 'add_nonterminal', 'modify_grammar']:
            jsgf_guidance = """
IMPORTANT: The development workflow includes an automated JSGF expansion and unit testing loop:
- After editing grammar files, developer runs: ./scripts/expand_grammar.sh
- This automatically generates test utterances and runs unit tests
- Developer iterates on grammar based on test failures
- Include realistic error→recovery cycles where appropriate
"""

        return f"""You are reconstructing an NLU developer's workflow for this subtask.

SUBTASK GOAL: {subtask.goal}
SUBTASK TYPE: {subtask.type}

{jsgf_guidance}

RELEVANT INSTRUCTIONS:
{instructions}

FINAL CODE CHANGES FROM GIT:
{commit_context}

AVAILABLE TOOLS:
{json.dumps(self.tools, indent=2)}

REQUIRED WORKFLOW STEPS (adapt as needed):
{json.dumps(template.get('required_steps', []), indent=2)}

COMMON ERRORS TO POTENTIALLY INCLUDE:
{json.dumps(template.get('typical_errors', []), indent=2)}

Generate a realistic step-by-step trajectory showing:
1. **Reasoning**: Explain why this action is needed
2. **Action**: Exact tool call with parameters in this format:
   **Action**: <tool_name>
   ```
   <parameter>: <value>
   ```
3. **Observation**: The result/output from the action

Be realistic - read files before editing, test after changes, fix errors when they occur.
Include 1-2 error recovery cycles if it makes sense for this subtask.

The trajectory should logically lead to the code changes shown in the commits.

Format your response as markdown with clear sections for each step.
"""

    def _build_critic_prompt(self, subtask: Subtask, trajectory: str,
                              diff_files: List[Dict]) -> str:
        """Build the critic prompt that evaluates a generated trajectory."""
        diff_summary = _format_diff_files(diff_files, max_chars=3000) or "(no diff data)"
        return f"""You are a critic reviewing an NLU developer trajectory for correctness and realism.

SUBTASK GOAL: {subtask.goal}

ACTUAL FILE CHANGES (from git diffs):
{diff_summary}

GENERATED TRAJECTORY:
{trajectory}

Evaluate the trajectory against these criteria:
1. Does it reference/address all changed files shown in the diffs?
2. Does it read files before editing them?
3. Does it include at least one test/validation step after changes?
4. Is there at least one realistic error or edge case handled?
5. Are tool call parameters concrete (real filenames, real content from diffs)?

Respond with valid JSON only (no markdown):
{{"approved": true/false, "feedback": "specific issues to fix, or empty string if approved"}}
"""

    def _build_revision_prompt(self, original_actor_prompt: str,
                                trajectory: str, feedback: str) -> str:
        """Build the revision prompt asking the actor to fix critic feedback."""
        return f"""{original_actor_prompt}

---

A previous attempt at this trajectory was rejected. Here is the critic's feedback:

FEEDBACK: {feedback}

Please revise the trajectory to address all the issues above. Output the complete revised trajectory.
"""

    # ── formatting helpers ────────────────────────────────────────────────────

    @staticmethod
    def _collect_diff_files(commits: List[Dict]) -> List[Dict]:
        """Collect all diff_files from a list of commit mapping entries."""
        result = []
        for item in commits:
            commit = item.get('commit', {})
            result.extend(commit.get('diff_files', []))
        return result

    def _format_commits(self, commits: List[Dict]) -> str:
        """Format commits (with diffs when present) for inclusion in prompt."""
        if not commits:
            return "No commit data available."

        formatted = []
        for item in commits:
            commit = item.get('commit', {})
            diff_section = ""
            diff_files = commit.get('diff_files', [])
            if diff_files:
                rendered = _format_diff_files(diff_files, max_chars=2000)
                if rendered:
                    diff_section = f"\nChanged files:\n{rendered}\n"

            formatted.append(
                f"Commit: {commit.get('short_id', 'unknown')}\n"
                f"Message: {commit.get('message', 'No message')}\n"
                f"Author: {commit.get('author_name', 'Unknown')}\n"
                f"Date: {commit.get('authored_date', 'Unknown')}"
                f"{diff_section}"
            )

        return "\n\n".join(formatted)


# ─────────────────────────────────────────────────────────────────────────────
# Main Transcript Generator
# ─────────────────────────────────────────────────────────────────────────────

class TranscriptGenerator:
    """Main orchestrator for transcript generation."""

    def __init__(self, llm_client: LLMClient, generic_instructions: str,
                 tool_schemas: Dict, max_tokens: int = 4000, temperature: float = 0.7,
                 no_critic: bool = False, max_critic_iterations: int = 2):
        self.llm = llm_client
        self.instructions = generic_instructions
        self.tools = tool_schemas
        self.max_tokens = max_tokens
        self.temperature = temperature

        self.requirements_parser = RequirementsParser(llm_client)
        self.commit_mapper = CommitMapper()
        self.trajectory_generator = TrajectoryGenerator(
            llm_client, tool_schemas, max_tokens, temperature,
            no_critic=no_critic,
            max_critic_iterations=max_critic_iterations,
        )
    
    def generate_transcript_from_epic(self, epic_data: Dict) -> Dict:
        """
        Generate training transcript from a Jira epic with commits.
        
        Args:
            epic_data: Dict with keys: jira_id, requirements, commits, merge_requests
            
        Returns:
            Dict with transcript and metadata
        """
        print(f"\n[Transcript] Processing epic: {epic_data.get('jira_id')}")
        
        # Stage 0: Parse requirements → subtasks
        print("[Transcript] Stage 0: Parsing requirements into subtasks...")
        subtasks = self.requirements_parser.parse_requirements_to_subtasks(
            epic_data['requirements'],
            self.instructions
        )
        print(f"[Transcript] Identified {len(subtasks)} subtasks")
        
        # Stage 1: Map commits → subtasks
        print("[Transcript] Stage 1: Mapping commits to subtasks...")
        commit_mapping = self.commit_mapper.map_commits_to_subtasks(
            subtasks,
            epic_data['commits']
        )
        
        # Stage 2: Generate trajectory per subtask
        print("[Transcript] Stage 2: Generating trajectories...")
        trajectories = []
        for subtask in subtasks:
            print(f"  - Generating trajectory for: {subtask.goal}")
            relevant_commits = commit_mapping.get(subtask.id, [])
            
            trajectory = self.trajectory_generator.generate_subtask_trajectory(
                subtask=subtask,
                commits=relevant_commits,
                instructions=self._get_relevant_instructions(subtask.type)
            )
            
            trajectories.append({
                'subtask_id': subtask.id,
                'subtask_type': subtask.type,
                'subtask_goal': subtask.goal,
                'trajectory': trajectory
            })
        
        # Stage 3: Combine and finalize
        print("[Transcript] Stage 3: Finalizing transcript...")
        full_transcript = self._combine_trajectories(trajectories, epic_data)
        
        return {
            'jira_id': epic_data.get('jira_id'),
            'transcript': full_transcript,
            'subtasks': [st.to_dict() for st in subtasks],
            'metadata': {
                'subtask_count': len(subtasks),
                'commit_count': len(epic_data.get('commits', [])),
                'subtask_types': [s.type for s in subtasks]
            }
        }
    
    def _get_relevant_instructions(self, subtask_type: str) -> str:
        """
        Extract relevant sections from generic instructions based on subtask type.
        
        For now returns full instructions, but could be enhanced to extract
        specific sections based on subtask type.
        """
        # TODO: Implement smart section extraction
        return self.instructions
    
    def _combine_trajectories(self, trajectories: List[Dict], 
                              epic_data: Dict) -> str:
        """Combine individual trajectories into a full transcript."""
        
        header = f"""# Training Transcript: {epic_data.get('jira_id')}

## Task Summary
{epic_data.get('requirements', 'No requirements specified')}

## Subtasks
{self._format_subtask_list(trajectories)}

---

"""
        
        body = "\n\n---\n\n".join([
            f"### {t['subtask_type'].replace('_', ' ').title()}: {t['subtask_goal']}\n\n{t['trajectory']}"
            for t in trajectories
        ])
        
        footer = f"""

---

## Task Complete

All subtasks completed successfully. Changes ready for review.
"""
        
        return header + body + footer
    
    @staticmethod
    def _format_subtask_list(trajectories: List[Dict]) -> str:
        """Format subtask list for header."""
        return "\n".join([
            f"{i+1}. **{t['subtask_type']}**: {t['subtask_goal']}"
            for i, t in enumerate(trajectories)
        ])


# ─────────────────────────────────────────────────────────────────────────────
# Tool Schemas
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "bash": {
        "description": "Execute a bash command",
        "parameters": {
            "command": "The shell command to execute"
        }
    },
    "file_read": {
        "description": "Read contents of a file",
        "parameters": {
            "path": "Path to the file",
            "lines": "Optional: line range [start, end] or 'all'"
        }
    },
    "file_modify": {
        "description": "Modify an existing file",
        "parameters": {
            "path": "Path to the file",
            "operation": "One of: insert_after, insert_before, insert_at_end, replace",
            "anchor": "Text to search for (for insert_after/before)",
            "old": "Text to replace (for replace operation)",
            "content": "New content to add/replace"
        }
    },
    "file_create": {
        "description": "Create a new file",
        "parameters": {
            "path": "Path for the new file",
            "content": "File contents"
        }
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def load_epic_data(epics_dir: Path, commits_file: Path, 
                   mr_refs_file: Path) -> List[Dict]:
    """
    Load epic data from jira_git_downloader output.
    
    Returns:
        List of epic data dicts ready for transcript generation
    """
    # Load MR references
    with open(mr_refs_file) as f:
        mr_refs = json.load(f)
    
    # Load all commits
    with open(commits_file) as f:
        all_commits = json.load(f)
    
    # Load each epic and associate commits
    epic_data_list = []
    
    for epic_file in epics_dir.glob("*.json"):
        with open(epic_file) as f:
            epic = json.load(f)
        
        epic_key = epic.get('key')
        
        # Find commits associated with this epic
        epic_commits = [
            c for c in all_commits 
            if epic_key in c.get('jira_issues', [])
        ]
        
        epic_data_list.append({
            'jira_id': epic_key,
            'requirements': _extract_requirements(
                epic.get('fields', {}).get('customfield_11232', '')),
            'summary': epic.get('fields', {}).get('summary', ''),
            'commits': epic_commits,
            'epic_metadata': epic
        })
    
    return epic_data_list


def load_generic_instructions(instructions_file: Path) -> str:
    """Load generic NLU development instructions."""
    if instructions_file.exists():
        with open(instructions_file) as f:
            return f.read()
    else:
        return "Generic NLU development instructions not provided."


# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--input-dir', type=Path, required=True,
                       help='Directory with jira_git_downloader output')
    parser.add_argument('--instructions', type=Path, required=True,
                       help='File with generic NLU development instructions')
    parser.add_argument('--output-dir', type=Path, default=Path('./transcripts'),
                       help='Output directory for training transcripts')
    parser.add_argument('--model', default='codellama/CodeLlama-13b-Instruct-hf',
                       help='Model name (HuggingFace model or claude-* for API)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of epics to process (for testing)')
    
    # Local model options
    parser.add_argument('--device', default='auto',
                       help='Device placement: auto, cuda, cpu (default: auto)')
    parser.add_argument('--load-in-8bit', action='store_true',
                       help='Load model in 8-bit quantization')
    parser.add_argument('--load-in-4bit', action='store_true',
                       help='Load model in 4-bit quantization (QLoRA)')
    parser.add_argument('--max-tokens', type=int, default=4000,
                       help='Maximum tokens to generate per request (default: 4000)')
    parser.add_argument('--temperature', type=float, default=0.7,
                       help='Sampling temperature (default: 0.7)')
    parser.add_argument('--no-critic', action='store_true',
                       help='Disable actor/critic loop (single-pass generation)')
    parser.add_argument('--max-critic-iterations', type=int, default=2,
                       help='Max critic refinement iterations per trajectory (default: 2)')

    args = parser.parse_args()
    
    # Validate input
    epics_dir = args.input_dir / 'epics'
    commits_file = args.input_dir / 'commits.json'
    mr_refs_file = args.input_dir / 'mr_refs.json'
    
    if not epics_dir.exists():
        print(f"ERROR: Epics directory not found: {epics_dir}")
        return 1
    
    if not commits_file.exists():
        print(f"ERROR: Commits file not found: {commits_file}")
        return 1
    
    if not args.instructions.exists():
        print(f"ERROR: Instructions file not found: {args.instructions}")
        return 1
    
    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data
    print("[Main] Loading epic data...")
    epic_data_list = load_epic_data(epics_dir, commits_file, mr_refs_file)
    
    if args.limit:
        epic_data_list = epic_data_list[:args.limit]
    
    print(f"[Main] Loaded {len(epic_data_list)} epics")
    
    # Load instructions
    print("[Main] Loading generic instructions...")
    generic_instructions = load_generic_instructions(args.instructions)
    
    # Initialize generator
    print("[Main] Initializing LLM client and generator...")
    llm_client = LLMClient(
        model=args.model,
        device=args.device,
        load_in_8bit=args.load_in_8bit,
        load_in_4bit=args.load_in_4bit
    )
    generator = TranscriptGenerator(
        llm_client=llm_client,
        generic_instructions=generic_instructions,
        tool_schemas=TOOL_SCHEMAS,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        no_critic=args.no_critic,
        max_critic_iterations=args.max_critic_iterations,
    )
    
    # Generate transcripts
    print(f"\n[Main] Generating transcripts for {len(epic_data_list)} epics...")
    
    results = []
    for i, epic_data in enumerate(epic_data_list, 1):
        print(f"\n{'='*80}")
        print(f"[Main] Processing epic {i}/{len(epic_data_list)}: {epic_data['jira_id']}")
        print(f"{'='*80}")
        
        try:
            result = generator.generate_transcript_from_epic(epic_data)
            results.append(result)
            
            # Save individual transcript
            output_file = args.output_dir / f"{epic_data['jira_id']}_transcript.json"
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            
            print(f"[Main] ✓ Saved transcript to: {output_file}")
            
        except Exception as e:
            print(f"[Main] ✗ Error processing {epic_data['jira_id']}: {e}")
            import traceback
            traceback.print_exc()
    
    # Save summary
    summary_file = args.output_dir / 'generation_summary.json'
    with open(summary_file, 'w') as f:
        json.dump({
            'total_epics': len(epic_data_list),
            'successful': len(results),
            'failed': len(epic_data_list) - len(results),
            'transcripts': [r['jira_id'] for r in results]
        }, f, indent=2)
    
    print(f"\n{'='*80}")
    print(f"[Main] Generation complete!")
    print(f"[Main] Successful: {len(results)}/{len(epic_data_list)}")
    print(f"[Main] Output directory: {args.output_dir.resolve()}")
    print(f"{'='*80}\n")
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
