# eval/

The test set, and later the code that scores both approaches against it.

| File | What it is |
|---|---|
| `03_build_questions.py` | Notebook, run by the job `juno-evalset`. Counts `human_labels` with SQL, gets the questions from `question_generator.py`, attaches the right answer to each, and writes the table `eval_questions` and `questions.json`. Ran once on 2026-09-20. The test set is frozen. |
| `question_generator.py` | The 7 question templates, the dev/test split and the question ids. Needs no data, so it is unit tested on the laptop. It is the record of how the questions were made. |
| `questions.json` | The 98 questions with their right answers: 28 dev, 70 test. A copy of `eval_questions`, kept in git so that any change to the frozen set shows. |

The scorers and the LLM judge's grading guide will be added here in the evaluation step.
