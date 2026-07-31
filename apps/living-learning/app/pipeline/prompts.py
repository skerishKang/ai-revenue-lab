"""Pipeline prompts for Living Learning."""

LESSON_PLAN_PROMPT = """You are a Korean AI/Python instructor creating a 10-minute lesson plan.

Topic: {topic}
Concept: {concept_name}
Learner preferences:
- example_preference: {example_preference}
- theory_density: {theory_density}
- jargon_level: {jargon_level}
- review_question_count: {review_question_count}

Create a lesson plan with:
1. A clear title
2. 3-4 sections covering the concept
3. One Python code example
4. {review_question_count} review questions

Output JSON with this schema:
{{
    "title": "string",
    "sections": [
        {{"section_id": "string", "title": "string", "description": "string", "emphasis": "string"}}
    ]
}}"""


LESSON_CONTENT_PROMPT = """You are a Korean AI/Python instructor creating lesson content.

Learner preferences:
- example_preference: {example_preference}
- theory_density: {theory_density}
- jargon_level: {jargon_level}
- pacing: {pacing_feedback_style}

Lesson plan:
{lesson_plan}

Create detailed content following the plan. Output JSON:
{{
    "content_version": "1.0",
    "title": "string",
    "sections": [
        {{
            "section_id": "string",
            "title": "string",
            "content": "string (Korean, with code blocks using ```python)",
            "includes_code": true,
            "code_snippet": "string"
        }}
    ],
    "review_questions": ["question1", "question2", "..."],
    "code_examples": [
        {{
            "example_id": "string",
            "language": "python",
            "code": "string",
            "explanation": "string",
            "expected_output": "string"
        }}
    ]
}}"""


ADAPTED_LESSON_PROMPT = """You are a Korean AI/Python instructor adapting a lesson based on learner feedback.

Original lesson plan:
{original_plan}

Learner feedback:
{direction_choices}

{free_text_section}

Create an ADAPTED lesson plan that addresses the feedback. Output JSON:
{{
    "title": "string (modified based on feedback)",
    "sections": [
        {{"section_id": "string", "title": "string", "description": "string", "emphasis": "string"}}
    ]
}}"""


EXERCISE_PROMPT = """Create a practice exercise for the concept: {concept_name}

Difficulty: {difficulty}
Language: Korean with Python code

Output JSON:
{{
    "question": "string (in Korean)",
    "options": ["option1", "option2", "option3", "option4"],
    "correct_answer": "string",
    "explanation": "string"
}}"""
ADAPTED_LESSON_CONTENT_PROMPT = """
You are generating the final lesson content for a second lesson, adapted from the original lesson based on learner feedback.
Original Plan: {original_plan}
Original Content: {original_content}
Feedback Directions: {direction_choices}
Feedback Text: {free_text_section}
Comprehension Understood: {comprehension_understood}
Comprehension Difficulty: {comprehension_difficulty}
Comprehension Text: {comprehension_text}
Adapted Plan: {lesson_plan}

Preferences:
- Example preference: {example_preference}
- Theory density: {theory_density}
- Jargon level: {jargon_level}

Output must align exactly with the adapted plan sections.
"""
