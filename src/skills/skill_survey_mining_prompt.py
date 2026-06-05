"""
Skill: survey_mining_prompt
===========================
Design survey-mining prompts for a new topic via structured interview.

When to use
-----------
- Creating a new topic and need survey-mining prompts (topic_desc, discovery_system, keyword_system)
- Refining an existing topic after high false-positive rate in Phase 1
- Switching research direction and need to re-scope what "survey" means for the new topic

Procedure (interactive interview)
---------------------------------
1.  **Understand the core research question**
    Ask: "What is the single-sentence definition of this topic?"
    Ask: "Is this primarily about mechanism design, detection/inference, or both?"
    Ask: "What is the end goal — a knowledge base, a formal survey paper, or keyword extraction?"

2.  **Build the classification framework**
    Ask the user to list the sub-directions they care about.
    Propose a starter framework (adapt to the topic):
    - Context window extension mechanisms
    - Context compression & selection
    - Memory architecture
    - KV-cache optimization
    - Context detection & inference (black-box / white-box)
    - Context injection attack / defense
    - Context interpretability
    Let the user add, remove, or refine categories.

3.  **Define inclusion & exclusion criteria**
    Inclusion: what MUST a paper be about to be considered relevant?
    Exclusion: what domains or directions are explicitly OUT of scope?
    Common exclusions to probe:
    - General RAG (unless about context budget)
    - General dialogue systems (unless about memory architecture)
    - Adversarial robustness / fairness / hallucination (unless tied to context length)
    - Unrelated domains (GNN, robotics, CV, bio, SE security, etc.)

4.  **Confirm false-positive tolerance**
    Ask: "What is the acceptable false-positive rate for Phase 1?"
    Typical: 5-15%. Lower tolerance means stricter prompts and possible manual review.

5.  **Confirm benchmark handling**
    Ask: "Should benchmark papers be included as survey candidates?"
    Rationale: benchmarks often contain comprehensive related-work sections,
    making them good keyword sources even if not formal surveys.
    If yes, restrict to benchmarks evaluating the target mechanism
    (e.g., "long-context benchmarks" for a context-management topic).

6.  **Confirm detection scope (if applicable)**
    If the topic includes "detecting / inferring" behavior:
    - Granularity: qualitative (strategy type) or quantitative (parameter inference)?
    - Methods: black-box side-channel, white-box interpretability, or both?
    - Target: open-source models, closed APIs, or both?

7.  **Assemble prompts**
    Build three blocks:
    - `topic_desc`: 1-2 paragraph narrative covering all included sub-directions
      and explicitly listing excluded domains.
    - `discovery_system`: system prompt for the LLM scanner.
      Must contain: (a) what a "survey" is, (b) inclusion list, (c) exclusion list,
      (d) output format `{"surveys": [index1, index2, ...]}`.
    - `keyword_system`: system prompt for keyword extraction from survey PDFs.

8.  **Validate & write back**
    Show the assembled prompts to the user for approval.
    Write to `topics/<name>.yaml` under the `survey_mining:` key.

Decision rules
--------------
- Err on the side of explicit exclusion lists. LLMs are better at excluding
  when told "do NOT include X" than at inferring implicit boundaries.
- Keep `topic_desc` and `discovery_system` in sync: anything in `topic_desc`
  should be actionable in `discovery_system` (i.e., expressible as inclusion/exclusion rules).
- If the user says "benchmarks count", add a restriction so only benchmarks
  evaluating the target mechanism are included, not general-domain benchmarks.

Validation
----------
- After writing prompts, run a small-batch test (100-500 papers) and manually
  review the top 20 candidates for false positives.
- False-positive rate > target → tighten exclusion list or add negative examples.
- False-positive rate < target but many misses → loosen inclusion criteria.

Integration points
------------------
- `topics/<name>.yaml` → `survey_mining.topic_desc`
- `topics/<name>.yaml` → `survey_mining.discovery_system`
- `topics/<name>.yaml` → `survey_mining.keyword_system`
- `stages/s03_survey_mining/core.py` → `build_discovery_prompt()` reads from topic config
"""

SKILL = {
    "name": "survey_mining_prompt",
    "version": "1.0",
    "category": "adapt",
    "description": "Design survey-mining prompts via structured interview for a new or refined topic",
    "trigger": "Creating a new topic or high false-positive rate in survey-mining Phase 1",
    "inputs": {
        "topic_name": "str — kebab-case topic identifier",
        "existing_yaml": "Path | None — existing topics/<name>.yaml to refine",
    },
    "outputs": {
        "topic_desc": "str — narrative description of the topic scope",
        "discovery_system": "str — LLM system prompt for survey discovery",
        "keyword_system": "str — LLM system prompt for keyword extraction",
        "yaml_path": "Path — where the prompts were written",
    },
    "steps": [
        "understand_core_research_question",
        "build_classification_framework",
        "define_inclusion_exclusion",
        "confirm_false_positive_tolerance",
        "confirm_benchmark_handling",
        "confirm_detection_scope",
        "assemble_prompts",
        "validate_and_write_back",
    ],
    "fallback_chain": [
        "tighten_exclusion_list",
        "add_negative_examples_to_prompt",
        "manual_review_of_candidates",
    ],
    # ── Reference Template (validated on llm-context-management) ──
    # Copy this structure into topics/<name>.yaml under the `survey_mining:` key.
    # Replace ALL {PLACEHOLDER} sections with your topic's specifics.
    "reference_template": {
        "topic_desc": """
{TOPIC_NAME}: {one-sentence definition of the topic}.
Core directions:
1. {SUB_DIRECTION_1}: {brief description with key techniques or concepts}.
2. {SUB_DIRECTION_2}: {brief description}.
3. {SUB_DIRECTION_3}: {brief description}.
   - {Sub-aspect A}: {description}.
   - {Sub-aspect B}: {description}.
4. {SUB_DIRECTION_4}: {brief description}.
5. {SUB_DIRECTION_5 (if detection/inference scope applies)}:
   - {Method type}: {description}.
   - {Another method}: {description}.
6. {OPTIONAL_ATTACK_DEFENSE}: {description if applicable}.
NOT included:
- {EXCLUSION_1}: {why it is out of scope}.
- {EXCLUSION_2}: {why it is out of scope}.
- {EXCLUSION_3}: {why it is out of scope}.
- {EXCLUSION_4 — unrelated domains}: {list domains}.
""",
        "discovery_system": """
You are a research librarian identifying survey/review/benchmark papers about {TOPIC_NAME}.
A "survey" must be one of: systematic review, literature review, survey, taxonomy,
OR a benchmark study that covers MULTIPLE works and evaluates {MEASURABLE_BEHAVIOR}.
Include ONLY if the paper is about:
- {SUB_DIRECTION_1}
- {SUB_DIRECTION_2}
- {SUB_DIRECTION_3}
- {SUB_DIRECTION_4}
- {SUB_DIRECTION_5 (optional)}
- {SUB_DIRECTION_6 (optional)}
EXCLUDE if about:
- {EXCLUSION_1}
- {EXCLUSION_2}
- {EXCLUSION_3}
- {EXCLUSION_4 — unrelated domains}
- {EXCLUSION_5 — unrelated domains}
Return JSON: {"surveys": [{"idx": 0, "title": "Exact Title"}, ...]}
Use the EXACT index and title from the list below. If idx and title mismatch, trust the title. NOTHING else.
""",
        "keyword_system": """
Extract technical keywords about {TOPIC_NAME} from these survey papers.
Return JSON: {"keywords": ["term1", "term2", ...]}
""",
    },
}
