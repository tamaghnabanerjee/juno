# Evaluation assets

Filled in during step 2 (questions and ground truth) and step 6 (the judge).

| File | Contents |
|---|---|
| `question_templates.yml` | The fill-in-the-blank question templates over the 12 categories |
| `judge_guidelines.md` | The LLM judge's rubric, versioned so changes to grading are reviewable |

Generated question sets and their correct answers are written to Unity Catalog tables, and the
frozen test split is committed here once it exists so the evaluation can be reproduced.
