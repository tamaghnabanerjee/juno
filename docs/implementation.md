# Implementation plan — Project Juno

This document says, step by step and in order, how the rest of Juno gets built. It was written on
2026-09-20. Submission is on Sunday 2026-09-27.

It sits beside three other documents and does not repeat them.

| Document | What it is |
|---|---|
| `docs/design-doc.pdf` | The two-page design submitted to the course on 2026-09-17. It says what Juno is, how it is measured, and which tools it uses. |
| `docs/design.md` | The rules for checking the tagger's labels and for reporting Juno's score. The project owner decided them on 2026-09-20. |
| `docs/reference.md` | A map of every table, column and file. |
| This document | The actions, in order, that turn those into a working system. |

The body of this document refers to AI models by their role. Model names, the workspace address and
other specifics are in Appendix A.

## Terms used in this document

| Term | Meaning |
|---|---|
| Sentence | One of the 5,152 English restaurant-review sentences in the dataset. |
| Topic | What a sentence is about. The dataset fixes 12 topics. |
| Label | One sentence, one topic and one sentiment together. A sentence can carry several. |
| Human labels | The labels that came with the dataset. They are treated as the truth. Table `human_labels`. Juno never reads them. |
| Tagger | The AI model that reads each sentence and writes its own labels. Table `review_facts`. Juno counts these. |
| Instructions | The page of text the tagger follows. |
| Approach A | The plain chatbot. It finds the 20 sentences closest to the question and answers from those. It is the baseline Juno must beat. |
| Approach B, or Juno | The agent. For each question it decides whether to count labels with a database query, to fetch example sentences, or both. It checks its numbers and cites the sentences it used. |
| Test questions | 98 questions with known true answers, generated from templates. 28 are the *development questions*, used while building. 70 are the *sealed questions*, run once at the end. |
| Agent model, judge model, tagger model, embedding model | The four AI models Juno uses, named by role. The judge grades answer quality and is deliberately a different model from the agent. The embedding model turns text into numbers so that similar sentences can be found. |
| Notebook, job, bundle | A notebook is a script that runs on Databricks. A job runs one or more notebooks in order. The bundle is the set of files in this repository that defines the jobs, so that they are deployed from code. |
| Profile | A saved sign-in for the Databricks command-line tool. This project uses one profile only. Appendix A names it. |

## Rules that apply to every step

1. **Nothing runs on Databricks until the project owner has approved that step's actions.** Approval
   of this document is not approval to run. Each step is approved when it is reached.
2. **Before any command, say what is about to run, where, and what it touches.**
3. **Every action below carries one of three tags.**

| Tag | Meaning |
|---|---|
| `[laptop]` | Runs on the laptop only. Costs nothing. |
| `[reads Databricks]` | Asks the workspace for information. Changes nothing. Costs nothing, or next to nothing. |
| `[runs on Databricks]` | Changes something in the workspace, or calls an AI model, or both. The step says what it costs where that is known. |

4. **The project owner confirms the profile before the first Databricks command of a session.** A
   second profile exists on the laptop for an older course workspace. It is never used here.
5. **Code changes come with tests.** `pytest -q` must pass on the laptop before anything is deployed.
   47 tests pass today. There were 28 before step 3a.
6. **The 70 sealed questions are run once, in step 8.** Everything before that uses only the 28
   development questions.
7. **No dataset sentence leaves the workspace.** The dataset has no licence file, so its sentences are
   never committed to the repository and never pasted into the tagger's instructions.
8. **Every step ends with an entry in the project log.** Failures and changes of direction are also
   collected for the README, which must document them (step 12).
9. **Nothing is committed to the repository unless the project owner asks.**

## Where things stand

| Step | What it builds | State on 2026-09-20 |
|---|---|---|
| 0 | Workspace, storage, catalog, repository, bundle | Done |
| 1 | The data tables | Done |
| 2 | The 98 test questions with true answers | Done |
| 3 | The tagger's labels, checked at two checkpoints | In progress. Three trial attempts made. Steps 3a and 3b done on 2026-09-20, and the workspace was asked which models it accepts for bulk use. Nothing run on the full data. |
| 4 | The search index over the sentences | Not started |
| 5 | Approach A, the plain chatbot | Not started. `src/juno/baseline.py` is a placeholder. |
| 6 | The evaluation framework, version 1, our own | Not started |
| 7 | Approach B, the Juno agent | Not started. `src/juno/agent.py` is a placeholder. |
| 8 | The final run on the 70 sealed questions | Not started |
| 9 | The evaluation framework, version 2, the MLflow route | Not started |
| 10 | The chat page | Not started |
| 11 | Access, guardrails and cost controls | A budget alert exists. The rest is not started. |
| 12 | README, documentation, demo video, public repository | Not started |

## Steps 0 to 2 — done

These are complete. They are listed so that a reader knows what the later steps rely on.

| What exists | Detail |
|---|---|
| A dedicated workspace, with its own storage | Set up by `infra/setup.sh`. Appendix A has the names. |
| Catalog `juno`, schema `restaurant`, volume `raw` | Created outside the bundle on purpose, so that removing the bundle can never delete the data. |
| Table `raw_sentences` | 5,152 rows. The dataset exactly as downloaded. |
| Table `sentences` | 5,152 rows. One per sentence. The id of a sentence is made by scrambling its text, so it is the same on every run. |
| Table `human_labels` | 6,547 rows. One per sentence, topic and sentiment. |
| Table `eval_questions`, and the file `eval/questions.json` | 98 questions: 28 development and 70 sealed. Generated by our own code in `src/juno/questions.py`. The same input always gives the same 98. |
| Jobs `juno-data` and `juno-evalset` | Kept separate so that rebuilding the data can never regenerate the questions. |
| Unit tests | 28 when steps 0 to 2 were finished, 47 after step 3a. They run on the laptop in well under a second and need no workspace. |

## Step 3 — the tagger's labels

### Purpose

Juno answers counting questions by counting the tagger's labels. This step produces those labels in
the table `review_facts`, and proves how far they can be trusted. `docs/design.md` sets the rules.
In short:

```
instructions → trial run on 1,500 sentences → CHECKPOINT 1 → full run on all 5,152 → CHECKPOINT 2
                        ▲                          │
                        └── adjust instructions ◀──┘ if it fails
```

Checkpoint 1 has two conditions. Condition 1: of the 10 "how many" questions big enough to mark, at
least 8 must have a tagger count within 10% of the human count. Condition 2: the tagger's average F1
score over the 12 topics must be at least 0.60. Checkpoint 2 marks all 18 "how many" questions once,
and the tagger is not changed afterwards.

### What existed before step 3a

| Thing | State on the morning of 2026-09-20 |
|---|---|
| `src/juno/tagging.py` | Held one version of the instructions. Its text matched the third attempt. |
| `src/juno/scoring.py` | The F1 score, the count comparison and the checkpoint 1 verdict, with tests. It had no 30-sentence minimum. |
| `src/notebooks/04_tagging.py` | Ran the tagger and the checks. It carried its own copy of the first attempt's instructions and never read `tagging.py`. |
| `resources/tagging.job.yml` | One job with two tasks. The full run started by itself as soon as the trial passed. |
| Four leftover tables in the workspace | `_tagging_sample`, `_tagging_sample_facts`, `_sample_v2`, `_sample_v3`. From the three attempts on 2026-09-20. |
| `review_facts` | Does not exist. Nothing has been run on the full data. |

### Step 3a — bring the code in line with `design.md`

**State: done on the laptop on 2026-09-20, approved by the project owner.** All 14 changes are made.
47 unit tests pass, up from 28. Nothing is committed and nothing is deployed. The one remaining action
was the `[reads Databricks]` check at the end of this step. The project owner confirmed the profile
and it passed on 2026-09-20. It recommended one job per file, so `resources/tagging.job.yml` became
`resources/tagging_trial.job.yml` and `resources/tagging_full.job.yml`, with the same contents.

All of these are `[laptop]`. None of them runs anything on Databricks.

| # | Change | File | Why |
|---|---|---|---|
| 1 | Keep each version of the instructions as its own named piece of text, with the reason for the change written beside it. The first version is recovered from the notebook's copy. The third is what the file holds now. The second was overwritten and cannot be recovered, and the file says so. | `src/juno/tagging.py` | `design.md` section 8 says changes to the instructions can be reviewed. Today they cannot. |
| 2 | Delete the notebook's own copy of the instructions. Read them from `tagging.py`. Save the version of the instructions and the name of the model with every set of labels. | `src/notebooks/04_tagging.py` | Running the job today would repeat the first attempt. |
| 3 | Add the 30-sentence minimum to checkpoint 1. The check receives the human count for each question. It marks a question only if that count is at least 30. It reports which questions were marked and which were skipped. | `src/juno/scoring.py`, `tests/test_scoring.py` | `design.md` section 4.2. Without it a good tagger fails two times in three. |
| 4 | Mark the 18 "how many" questions, not every topic-and-sentiment combination that appears in any question. | `src/notebooks/04_tagging.py` | Today 20 combinations are marked. Two of them have no "how many" question. |
| 5 | Make the trial run 1,500 sentences by default. | `resources/tagging.job.yml`, `src/notebooks/04_tagging.py` | `design.md` section 4.1. Today the default is 500. |
| 6 | Split the job in two: a trial job and a full-run job. The full run never starts by itself. | `resources/tagging.job.yml` | Two models must be compared and a winner picked before anything is labelled in full. Today a passing trial starts the full run at once. |
| 7 | Save the result of every trial run as one row in a new table, `tagging_trials`: the model, the version of the instructions, the number of sentences, the questions marked, the ticks, the average F1 score, the verdict and the time. | `src/notebooks/04_tagging.py` | This is the evidence for the comparison, and it goes in the README. |
| 8 | Add the rule that picks the better of two models, in the four-step order of `design.md` section 7, with tests for each step. | `src/juno/scoring.py`, `tests/test_scoring.py` | The rule was fixed before any result exists. Code and tests make it impossible to bend later. |
| 9 | Make the full run refuse to start unless `tagging_trials` holds a passing row for the same model and the same version of the instructions. Stop the full run from labelling the trial sentences a second time. | `src/notebooks/04_tagging.py` | Today, running the notebook directly in full-run mode skips checkpoint 1. |
| 10 | After the full run, save checkpoint 2 as a table, `checkpoint2`, with one row for each of the 18 questions: the human count, the tagger's count, how far off, and tick or cross. Nothing stops on a cross. The table governs what the report says. | `src/notebooks/04_tagging.py` | `design.md` sections 5 and 6. Today the numbers are printed and nothing depends on them. |
| 11 | After the full run, work out both measures again on the 3,652 sentences that were never in the trial run, and save them as `tagging_quality_untouched`. | `src/notebooks/04_tagging.py` | `design.md` section 6. This is the honest figure for the tagger's general quality. |
| 12 | Before any labelling, check that no sentence of the dataset appears inside the instructions, and stop if one does. This check has to run on Databricks, because the sentences are not on the laptop. | `src/notebooks/04_tagging.py` | `design.md` section 8. Today nothing enforces the rule. |
| 13 | Ask the platform to return an error for a sentence that fails, in place of stopping the whole run. Count and report the sentences whose reply could not be read. | `src/notebooks/04_tagging.py` | One bad reply in 5,152 should not sink a run that costs money. |
| 14 | Bring `docs/reference.md` in line. It plans a `confidence` column in `review_facts` that the design does not use. | `docs/reference.md` | The map must match the territory. |

**How we know it worked.** `pytest -q` passes, with new tests for changes 3 and 8. Then one
`[reads Databricks]` action: `databricks bundle validate -t dev`, with the profile from Appendix A.
It checks the job definitions against the workspace and changes nothing.

### Step 3b — see which models the workspace offers, and which it accepts for bulk use

**State: done on 2026-09-20, approved by the project owner.**

| Action | Tag | What it found |
|---|---|---|
| List the workspace's model endpoints | `[reads Databricks]` | 11 chat models and 3 embedding models. The model first chosen as the preferred tagger is not among them. |
| Put every chat model through the platform's bulk function on two rows, with a fixed prompt and no review text | `[runs on Databricks]`. Cost: 18 calls of a few words, and a few minutes of the SQL warehouse. | The bulk function accepts one closed-source model and all eight open models. It refuses two closed-source models, one of which the platform's documentation lists as supported. |

**What was decided from it.** The project owner fixed two tagger candidates: the one closed-source
model the workspace accepts for bulk use, which is preferred, and one open model, named in the project
log before its first trial run. Appendix A names both. `docs/design.md` section 7 and its Appendix A
have the full result.

**The lesson carried forward.** The documentation's list was wrong for this workspace in both
directions. Whatever a later step relies on is checked in the workspace first.

### Step 3c — try both candidates on five sentences, with the real instructions

**State: done on 2026-09-20, approved by the project owner.** The bundle was deployed: the two tagging
jobs exist and the old one is gone. For both candidates, 0 of 5 sentences failed and 0 of 5 replies
were unreadable; every reply was a clean list with no formatting marks around it. Checkpoint 1
reported "failed" for both, as expected with five sentences. Five sentences say nothing about quality.
The cost could not be read: the workspace's billing table is closed to the project owner's sign-in, and
opening it is the account owner's decision. The "What costs money" table below has an estimate from
published prices in its place.

**Why it is still needed.** Step 3b showed that the bulk function accepts both candidates. It used a
fixed prompt. It did not show what their labels look like, whether the notebook can read their
replies, or what a call costs. Five sentences settle the first two for almost nothing, and give a
first figure for the third, before a trial run of 1,500 is spent.

**Actions, in order.**

1. `[runs on Databricks]` Deploy the bundle to the development setting. **This changes the
   workspace**: it creates the jobs `juno-tagging-trial` and `juno-tagging-full`, and removes the old
   job `juno-tagging`, which the bundle no longer defines. It costs nothing.
2. `[runs on Databricks]` Run the trial job with a trial size of 5, once for each candidate. The
   cost is ten model calls with the full instructions. Because the real notebook runs, this also tests
   the notebook itself: the check for dataset sentences in the instructions, the reading of replies,
   and the saving of a row to `tagging_trials`.
3. `[reads Databricks]` Look at the saved replies by sentence id. No review text is brought back.
4. `[reads Databricks]` Read the cost of the two runs from the workspace's billing table. That table
   can lag by some hours.

**What we look for.**

| What | Expected | If not |
|---|---|---|
| Sentences that failed | 0 of 5 | Read the platform's message |
| Replies that could not be read | 0 of 5 | Look at the raw reply. A model that wraps its reply in formatting marks would lose labels, which would be unfair in a comparison. The fix is a clearer format line in the instructions, or reading replies more tolerantly, and either one is the project owner's decision. |
| Labels | Only the 12 topics and the three sentiments | The notebook already drops anything else |
| Checkpoint 1 | "Failed", and that is expected. With five sentences no question reaches 30, so nothing can be marked. | — |

The two rows this writes to `tagging_trials` carry a trial size of 5. Every comparison reads only rows
of one trial size, so they never mix with the real trials.

### Step 3d — trial runs for both models, checkpoint 1, and the winner

Two actions, both `[runs on Databricks]`. Each is one run of the trial job on the same 1,500
sentences, with the third version of the instructions. One run uses the preferred candidate. The other
uses the second candidate. Everything else is identical, so the model is the only thing that differs.

**Cost.** Not known for either candidate. The project log records the three earlier attempts, made
with a third model on 1,500 sentences in total, as costing "cents"; no exact figure was kept. The
preferred candidate belongs to the most expensive tier of its family. Step 3c gives a first figure for
both, and the project owner sees it before approving this step.

**What each run produces.** One row in `tagging_trials`, and a printed report: every question's human
count and tagger count, the ones marked and the ones skipped, the F1 score for each topic, the average
F1 score, and the verdict for each condition.

**Picking the winner.** The rule from `design.md` section 7, applied by the code from change 8:

1. A model that meets both conditions beats one that does not.
2. If both meet them, or neither does, the higher average F1 score wins.
3. If the average F1 scores are equal to two decimal places, the model with more ticks wins.
4. If still equal, the preferred order in `design.md` Appendix A decides.

**How we know it worked.** Each run labels exactly 1,500 sentences. 10 questions are marked and 8 are
skipped, as the table in `design.md` section 4.2 predicts. The human counts inside the trial are close
to that table's third column. Both rows are in `tagging_trials`.

### Step 3e — if the winner fails checkpoint 1

1. `[laptop]` Read the report. The crosses show which questions are off and in which direction. The
   lowest topic scores show which topics the instructions handle badly.
2. `[laptop]` Write a new version of the instructions in `tagging.py`, with the reason beside it.
   Examples in the instructions are written by hand, never taken from the dataset.
3. `[runs on Databricks]` Run the trial job again on the same 1,500 sentences.

`design.md` contains a paragraph about how many attempts are allowed. The project owner parked that
question on 2026-09-20. This plan adds nothing to it.

### Step 3f — the full run and checkpoint 2

One action, `[runs on Databricks]`: the full-run job, once, with the winning model and the version of
the instructions that passed. It labels all 5,152 sentences into `review_facts`, then writes
`checkpoint2` and `tagging_quality`.

**After this action the tagger is not changed.** Not the model and not the instructions. `design.md`
section 5 explains why: changing it after looking at all the data would fit it to the whole answer
key.

**How we know it worked.**

| Check | Expected |
|---|---|
| `review_facts` has one row for each sentence, topic and sentiment | The same shape as `human_labels`. No duplicates. |
| The human count for "the service, negatively" | 466. The notebook already stops if it is anything else, because that would mean the truth itself had changed. |
| `checkpoint2` | 18 rows, each with a tick or a cross |
| Sentences for which no usable labels came back | Counted and reported. A sentence that is about none of the 12 topics rightly has none. |

**What the result means.** `design.md` section 6 governs it. Juno is scored on 13 of the 18 "how
many" questions and needs 11 of them right. The crosses in `checkpoint2` say, before Juno is built,
which questions it cannot get right.

### Step 3g — the tagger's general quality

Produced by the same run as step 3f, through change 11. Both measures, worked out only on the 3,652
sentences that no adjusting ever touched. It is reported in the README. It is not a pass or fail
condition.

### Step 3h — clean up

One action, `[runs on Databricks]`, at no cost: delete the four leftover tables from the first three
attempts, and the trial label tables once their results are safely in `tagging_trials`.

### What could go wrong in step 3

| Trap | Where it is known from | What to do |
|---|---|---|
| Jobs on this workspace cannot use the machine's own disk. | Project log, 2026-09-19: the first download failed for this reason. | Write only to the volume or to tables. |
| The first run of a job can take about 10 minutes, most of it start-up. | Project log, 2026-09-19. | Expect it. It is not a fault. |
| A model's reply is not in the requested format. | Not yet seen. | Change 13 counts such replies. If they are more than a few, the instructions need a clearer format line. |
| Two attempts with identical settings give slightly different labels. | AI models do not always repeat themselves exactly. | Never compare a fresh run with an old one. Compare rows in `tagging_trials`. |

## Step 4 — the search index

### Purpose

Both approaches need to find sentences that are close in meaning to a question. Approach A takes the
20 closest of all sentences. Juno takes up to 10, and only from sentences that carry a given topic and
sentiment, to use as the examples behind a "why" answer.

### What gets built

| Thing | What it is |
|---|---|
| A search endpoint | The platform's service that holds indexes. **It is billed for every hour it exists**, so it is created at the start of this step and deleted once the demo video is recorded. |
| An index that follows a table | The platform turns each sentence into numbers with the embedding model and keeps the index in step with the table. |
| `find_examples()` in `src/juno/retrieval.py` | Today a placeholder. It returns up to `k` sentences with their ids. |

### Actions, in order

1. `[laptop]` Decide the shape of the table the index follows. See the open decision below.
2. `[runs on Databricks]` Build that table from `sentences` and `review_facts`.
3. `[runs on Databricks]` Turn on the table's change history. **The platform requires this before the
   index is created.** The project log recorded it as a trap on 2026-09-19.
4. `[runs on Databricks]` Create the search endpoint, then the index. **Every column used as a filter
   must be listed among the columns the index copies**, or the filter fails without an error. This is
   also a trap from the project log.
5. `[laptop]` Write `find_examples()`, with tests that use a stand-in for the search service.
6. `[runs on Databricks]` Try three searches by hand.

### Open decision at this step — what one row of the index is

A sentence can carry several labels, and a filter needs one topic and one sentiment to test.

| Option | What one row is | Good | Bad |
|---|---|---|---|
| One index, one row per label | A sentence with two labels appears twice | Filtering is simple | Approach A would see duplicates and must drop them. Sentences with no labels are missing, which handicaps A unfairly. |
| Two indexes | One of plain sentences for A, one of labelled rows for Juno | Each approach searches exactly what it should. A behaves like an ordinary chatbot. | Two indexes to keep. The submitted design says "the same index". |
| One index, one row per sentence, with the labels packed into a text column | Every sentence appears once | One index, fair to A | Depends on the platform's filters accepting a "contains" test. This has not been checked. |

This is decided when the step starts, after the platform's filter rules have been read.

### How we know it worked

| Check | Expected |
|---|---|
| Rows in the index | The same number as rows in the table it follows |
| A search for "rude waiter" with no filter | Sentences about staff |
| The same search filtered to the service, negative | Only sentences that carry that label in `review_facts` |

## Step 5 — approach A, the plain chatbot

### Purpose

The course requires a comparison of at least two approaches, and warns against skipping a simple
baseline. A is that baseline. It is built before Juno so that there is always something to measure
against.

### The common doorway

Both approaches answer through the same doorway, so that the same scoring works on both and a third
approach could be plugged in later. A question goes in. This comes out:

| Field | Meaning | Who fills it |
|---|---|---|
| `answer_text` | The answer in words | Both |
| `number`, `unit` | The figure the answer states, and whether it is a count of sentences or a percentage | Both, when the question asks for a figure |
| `topics` | An ordered list of topics, for questions about top topics or comparisons | Both, when asked |
| `sentence_ids` | The sentences cited as evidence | Both |
| `sql_number` | The figure that came back from Juno's own database query | Juno only |
| `seconds`, `tokens_in`, `tokens_out` | Time taken and the amount of text sent to and returned by the model, from which cost is worked out | Both |

### Actions, in order

1. `[laptop]` Write the doorway as a small shared definition.
2. `[laptop]` Write `answer()` in `src/juno/baseline.py`: fetch the 20 closest sentences, give them to
   the agent model with the question, and ask for the fields above. Tests use a stand-in model.
3. `[runs on Databricks]` Ask it three of the development questions by hand.

### How we know it worked

It returns every field. On a counting question its figure describes 20 sentences, not 5,152, so it is
expected to be far off. That is the point of the baseline.

### Open decision at this step

Whether the code calls the models through the platform's connector for LangGraph or directly. Both
work for A. It matters more in step 7, and is decided once for both.

## Step 6 — the evaluation framework, version 1

### Purpose

This is the part of the project that produces every reported result. It is our own code. MLflow only
keeps the records.

**This is a change of direction from the submitted design**, which said "MLflow scores A and B" and
chose MLflow for "traces, scorers and LLM judges in one place". The project owner decided the change
on 2026-09-20. The reason: the course teaches building evaluations (curriculum, Week 7: "Build evals
for AI apps with LLM as a judge, manual SME queries, and Eval frameworks"). What stays the same: the
questions, the measures and the pass marks. The results are still written into MLflow, so they remain
viewable in one place. The README records this under failures and pivots.

### What gets built

A small package, `src/juno/evals/`, in the style of `questions.py` and `scoring.py`: plain functions
that can be tested on the laptop.

| Part | File | What it does |
|---|---|---|
| Runner | `runner.py` | Takes an approach and a list of questions. Sends each question through the doorway. Saves every answer. Never looks at the true answers. |
| Scoring functions | `scorers.py` | One per measure. Each takes one saved answer and the true answer and returns a score. |
| Judge | `judge.py`, `eval/judge_guidelines.md` | The written grading guide, the call to the judge model, and the check of the judge against grades given by hand. |
| Report | `report.py` | The results tables: each measure against its pass mark, A against Juno, and the three numbers of `design.md` section 10. |
| Store | `store.py` | Writes answers and scores to tables, and the same figures and the step-by-step records into MLflow. |

### The measures

The measures and pass marks are those of the submitted design.

| Measure | Questions it applies to | How one answer is scored | Pass mark |
|---|---|---|---|
| Count accuracy | "How many" | 1 if the stated figure is within 10% of the true figure, else 0. Example: true 466, stated 480. The gap is 14. 14 ÷ 466 = 3.0%, so the score is 1. | 1 on at least 80% of questions, and at least 30 points above A |
| Top-3 match | Top topics | The share of the true top 3 that appear in the stated top 3 | An average of at least 0.8 |
| Citation accuracy | "Why" | The share of cited sentences that are in the true set for that topic and sentiment | At least 90% |
| Answer quality | "Why" | The judge model grades the answer from 1 to 5 against the grading guide | An average of at least 4 |
| Exact number | Juno's counting answers | 1 if the stated figure equals the figure from Juno's own database query, else 0 | At least 95% |
| Speed | All | Seconds per question | A median of 15 seconds or less |
| Cost | All | Worked out from the amount of text sent and returned | Measured, no pass mark |

### The judge, and the check on the judge

1. `[laptop]` Write the grading guide in `eval/judge_guidelines.md`: what a 1, 2, 3, 4 and 5 look
   like for a "why" answer.
2. `[runs on Databricks]` Produce answers to the development "why" questions from both approaches.
3. The project owner grades 30 of those answers by hand, **before seeing the judge's grades**, so that
   the hand grades cannot lean towards the judge.
4. `[runs on Databricks]` The judge model grades the same 30.
5. `[laptop]` Compare: how often the two grades are equal, and how often they are within one point.

The answers can quote review sentences. So the 30 graded answers are kept in a table in the workspace.
Only the question ids and the grades are committed.

### Actions, in order

1. `[laptop]` Scoring functions, each with hand-made test cases. No workspace needed.
2. `[laptop]` Runner and store, tested with a stand-in approach.
3. `[runs on Databricks]` Run approach A over the 28 development questions and score it. This is the
   first real use of the framework.
4. The judge steps above.
5. `[laptop]` Report.

### How we know it worked

Every scoring function passes its tests. A full run over the 28 development questions saves one
answer per question and one score per measure that applies. Running the scoring twice on the same
saved answers gives identical figures for every measure except the judge's.

### Open decisions at this step

| Question | Why it is open |
|---|---|
| Are the 18 "what share" and 18 "share within a sentiment" questions scored under count accuracy? | They rest on the same 18 counts. The submitted design says count accuracy applies to "how many". Nothing settles it. |
| How is a "which is bigger" question scored? There are 16. | The submitted design's table has no row for them. The natural score is 1 for naming the right one. |
| What agreement with the 30 hand grades makes the judge trustworthy? | The submitted design requires the check and sets no pass mark. |
| Should a small set of questions written by hand be added? | All 98 come from templates. The curriculum mentions "manual SME queries", meaning questions written by someone who knows the subject. They could be added as a separate, labelled set without touching the frozen 98. |

## Step 7 — approach B, the Juno agent

### Purpose

This is the system the project is about. It is built with LangGraph, as the submitted design said,
because LangGraph lets the agent be written as a small graph of steps that can each be tested.

### What gets built

```
question → the agent model reads it and picks a tool
               ├─ count_sql:     counts labels in review_facts through a fixed query
               └─ find_examples: fetches up to 10 sentences with a given topic and sentiment
           → check: does every figure in the draft equal a figure a query returned?
               ├─ yes → answer, with the cited sentence ids
               └─ no  → one retry. If it fails again, the answer states the query's figure.
```

| Part | State | Detail |
|---|---|---|
| `count_sql` | Built and tested. `src/juno/counting.py`. | The model never writes a database query. It picks a topic, a sentiment and a grouping from fixed lists. Anything else is rejected, so text smuggled into a question cannot reach the database. |
| `find_examples` | Built in step 4 | At most 10 sentences, the limit the submitted design commits to |
| The check step | To build | The guard against made-up numbers |
| Declining | To build | Juno declines anything that is not about the reviews |
| The wrapper for deployment | To build | The agent is wrapped in MLflow's standard agent shape so that it can be registered and served (step 10) |

**Memory.** Juno keeps a working state for the length of one question: the question, what the tools
returned, and the draft answer. It keeps nothing between questions. This is deliberate. Each of the 98
test questions must get the same answer whatever was asked before it, or a run could not be repeated
or compared. Remembering the earlier turns of a conversation is an enhancement for later. See
"Enhancements for later", after step 12.

**What kind of system this is.** Approach A is retrieval-augmented generation: a fixed path of search,
then answer. Juno is agentic: the agent model chooses between two tools, and a check step can send it
round once more. Juno also retrieves, through `find_examples`, as one tool among two. Both approaches
use the same vector store, the search index of step 4.

### Actions, in order

1. `[laptop]` The graph, with a stand-in model, and tests for the check step: a draft with the right
   figure passes, a draft with a wrong figure is retried once, and a second wrong draft falls back to
   the query's figure.
2. `[runs on Databricks]` Ask it the development questions. Read the step-by-step records in MLflow.
3. `[laptop]` Adjust the agent's own instructions. **Only the 28 development questions are ever used
   for this.**
4. `[runs on Databricks]` The diagnostic of `design.md` section 10: point Juno's counting at
   `human_labels` in place of `review_facts`, on the development questions only. This shows how Juno
   does when the labels are perfect. It is labelled a diagnostic wherever it appears.

### How we know it worked

On the development questions, scored by version 1: the exact-number measure is at or near 100%,
because the check step enforces it. Count accuracy is 1 on the development questions that
`checkpoint2` marked with a tick. Every "why" answer cites sentence ids.

### What could go wrong

| Trap | What to do |
|---|---|
| The model maps a plain phrase to the wrong topic, for example "prices" to food prices. | The questions use plain phrases on purpose. Mapping them is part of what is measured. Fix it in the agent's instructions, on development questions only. |
| Adjusting Juno until the development scores look perfect. | The development questions are only 28. The sealed 70 decide. |

## Step 8 — the final run

### Purpose

The one run that produces the reported results.

### Before it starts

| Check | Why |
|---|---|
| The code is committed and the commit is written down | The run can be tied to exact code |
| The versions of the tagger's instructions, the agent's instructions and the grading guide are written down, with the model for each role | The run can be repeated |
| The sealed questions have never been run | The design's promise. Checked from the saved-answers table and the MLflow records. |
| The project owner approves the run | Rule 1 |

### Actions, in order

1. `[runs on Databricks]` The runner sends the 70 sealed questions through approach A and through
   Juno, once each. Every answer is saved to a table, `eval_answers_final`.
2. `[runs on Databricks]` Version 1 scores the saved answers. The judge grades the "why" answers.
3. `[laptop]` The report.

**If the run breaks part-way for a technical reason**, such as a timeout, only the questions that got
no answer are run again. Nothing about either approach is changed in between, and the log records
what happened. This rule is fixed now so that it cannot be bent later.

### What the report contains

Governed by `design.md` sections 6 and 10. Each measure against its pass mark, for A and for Juno.
Juno is scored on 13 "how many" questions and needs 11 right. If the target is missed it is reported
as missed, and the questions that `checkpoint2` marked with a cross are listed by name. Juno's score
on the remaining questions is shown separately, labelled as a measure of Juno's own part. Beside it
go Juno's own accuracy from the development questions, and the difference, which is the cost of
imperfect labels.

## Step 9 — the evaluation framework, version 2, the MLflow route

### Purpose

To learn the route the submitted design described, and to check version 1 against it. Version 2 is
not the source of any reported result.

### What gets built

| Part | How it differs from version 1 |
|---|---|
| Scoring functions | The same functions from `scorers.py`, wrapped in MLflow's format. Nothing is rewritten, so the two versions cannot drift apart. |
| Judge | MLflow's judge builder, given the same grading guide |
| Runner | MLflow's own evaluation function. It is given `eval_answers_final`, the answers saved in step 8. The Databricks reference notes confirm that it can score answers that were saved earlier, without calling the approach again. |

So the sealed questions are still run only once.

### Actions, in order

1. `[laptop]` The wrappers, with tests that each wrapped function returns what the plain one returns.
2. `[runs on Databricks]` Try it on the saved development answers first.
3. `[runs on Databricks]` Run it on `eval_answers_final`.
4. `[laptop]` Compare the two versions, question by question.

### How we know it worked

Every measure that is plain arithmetic must agree exactly between the two versions. The judge's grades
may differ, because the judge is called afresh, so the agreement between the two sets of grades is
reported. **If the versions disagree, version 1 is the reported figure**, and the difference is
investigated and written up.

### When

After step 8. If time runs short, this step can finish after 2026-09-27 without touching what is
submitted.

## Step 10 — the chat page

### Purpose

So that a person can use Juno. The course marks a user interface as optional. The project log records
a standing decision that it is in scope.

### What gets built

A page hosted by the platform. Each question goes to both approaches. The two answers appear side by
side, with Juno's cited sentences under its answer. A thumbs-up or thumbs-down on an answer is saved
onto that answer's record in MLflow.

### Actions, in order

1. `[runs on Databricks]` Serve both approaches behind endpoints. **The agent's endpoint stays out of
   the bundle**, because the platform's own deployment command owns it. This is a trap from the
   project log.
2. `[laptop]` The page.
3. `[runs on Databricks]` Deploy it. **The page runs as its own identity and needs to be granted
   access** to the two endpoints and nothing else. Also a trap from the project log.
4. Try it by hand, then record the demo (step 12).

### Open decision at this step

Which toolkit the page is written with. The platform's default is a TypeScript toolkit. This is a
one-person Python project, so a Python page is the likely choice. Decided when the step starts.

## Step 11 — access, guardrails and cost controls

These come from the appendix of the submitted design. Each row is something to set up and then to
check.

| Control | What is done | How it is checked |
|---|---|---|
| Who can open the page | Workspace sign-in. Access for named people only. | Someone without access is refused. |
| What the page can reach | Its own identity, allowed to call the two endpoints only | The identity's grants are listed and nothing else is there. |
| What Juno can read | Read-only access to Juno's tables and the index | An attempt to write is refused. |
| Where model keys are kept | In the platform's gateway, never in code or notebooks | The repository is searched for keys before it is made public. |
| Questions that are not about the reviews | Juno declines them (step 7) | Three such questions are asked. |
| Text smuggled into a question to change the database | Fixed query, fixed lists, read-only | Already tested in `tests/test_counting.py` |
| Unsafe or personal content | The gateway's filtering of requests and replies | One test request |
| Made-up numbers | The check step (step 7) | The exact-number measure |
| Runaway use | Limits per person and per endpoint, one retry, and a time limit per question | The limits are shown in the gateway's settings. |
| Spend | A monthly budget with an email alert | Exists. Set on 2026-09-19. |
| Cost per question | Added up from the MLflow records | The report in step 8 |

## Step 12 — the write-up

### What the course requires

| Deliverable | Limit |
|---|---|
| Design document | 1 to 2 pages. Submitted on 2026-09-17. |
| Code repository | Access for the reviewers |
| Documentation | 4 to 5 pages at most |
| Demo video | 3 minutes |
| A README section on "attempted approaches, failures, and subsequent pivots" | Required |

### Failures and pivots collected so far

| What happened | When |
|---|---|
| The first download failed, because jobs on this workspace cannot use the machine's own disk. | 2026-09-19 |
| Three tagging attempts failed checkpoint 1. They were marked under rules that reject even a good tagger 98 times in 100. | 2026-09-20 |
| Three tagging runs were made before the design had been reviewed. The sequence was wrong. | 2026-09-20 |
| One closed-source model was refused for bulk use, and the design wrongly concluded that its whole family was unusable. The platform's documentation showed otherwise. | 2026-09-20 |
| The number 30 and the number 0.60 were set without a recorded reason. They were kept as judgement numbers, and 30 was checked afterwards by calculation. | 2026-09-20 |
| A second checkpoint was added, because the first cannot see 8 of the 18 counting questions. | 2026-09-20 |
| The evaluation changed from MLflow doing the scoring to a framework of our own that reports into MLflow. | 2026-09-20 |

### Actions, in order

1. `[laptop]` README: what Juno is, the results table, A against Juno with the justified choice, and
   the failures and pivots.
2. `[laptop]` Bring every document in line with what was built. One known case: the README's run
   command names a job that does not exist under that name.
3. `[runs on Databricks]` Deploy once under the production setting, so that job names in the video
   carry no personal prefix.
4. Record the 3-minute video.
5. `[runs on Databricks]` Delete the search endpoint, so that it stops costing money.
6. `[laptop]` Check that no dataset sentence, no course material and no key is in the repository.
7. Make the repository public. Only on the project owner's word.

## Enhancements for later

These are not part of this build. They are recorded so that the choice is visible.

| Enhancement | What it would add | Why it is not in this build | What it would touch |
|---|---|---|---|
| Conversation memory, to make Juno a chatbot | Juno would remember the earlier turns of a conversation, so that a follow-up such as "and what about the food?" makes sense. | Decided by the project owner on 2026-09-20. The evaluation needs every question answered on its own, so that a run can be repeated and compared. The plan to 2026-09-27 is also tight. | The chat page (step 10) and the agent's wrapper. LangGraph has a built-in way to save the state of a conversation under a conversation id. The agent that is evaluated, and the 98 test questions, would not change. Follow-up questions would need test questions of their own before any claim was made about them. |

## A day-by-day plan

This is an estimate. It is tight. Steps 9 and 10 are the ones that can give way: the course marks the
user interface as optional, and step 9 exists for learning.

| Day | Steps |
|---|---|
| Monday 21 September | 3a, 3b, 3c |
| Tuesday 22 September | 3d, and 3e if needed |
| Wednesday 23 September | 3f, 3g, 3h, and step 4 |
| Thursday 24 September | Step 5, and the scoring functions and runner of step 6 |
| Friday 25 September | The judge and the 30 hand grades of step 6. Step 7 begins. |
| Saturday 26 September | Step 7 finishes on the development questions. Step 8. Step 10 begins. |
| Sunday 27 September | Steps 10, 11 and 12. Submission. |
| After submission, or earlier if time allows | Step 9 |

## Decisions still open

| # | Question | Decided at | State |
|---|---|---|---|
| 1 | How many attempts at checkpoint 1 are allowed | Step 3e | Parked by the project owner on 2026-09-20 |
| 2 | Which open model is the second tagger candidate | Step 3b | Decided on 2026-09-20 and named in the project log before its first trial run. Only that one is tried. Appendix A names it. |
| 3 | What one row of the search index is | Step 4 | Open |
| 4 | Calling the models through the platform's connector for LangGraph, or directly | Step 5 | Open |
| 5 | Whether the two kinds of "share" question count towards count accuracy | Step 6 | Open |
| 6 | How a "which is bigger" question is scored | Step 6 | Open |
| 7 | What agreement with the 30 hand grades makes the judge trustworthy | Step 6 | Open |
| 8 | Whether to add a small set of questions written by hand | Step 6 | Open |
| 9 | Which toolkit the chat page uses | Step 10 | Open |
| 10 | How decisions are attributed in documents that will be public | Step 12 | Open |

## What costs money

| Thing | When | What is known |
|---|---|---|
| Asking the workspace which models it accepts for bulk use | 3b, done | 18 calls of a few words, and a few minutes of the SQL warehouse |
| Five-sentence test of both candidates | 3c | Ten model calls with the full instructions |
| Trial runs of 1,500 sentences | 3d, 3e | Estimated from published prices, per run: about $7.50 with the preferred candidate and about $0.70 with the second. Working: the instructions are 3,270 characters, about 818 tokens; with the sentence that is about 845 tokens in and 30 out for each sentence, so 1.27 million in and 0.045 million out for 1,500. Appendix A has the prices. Not measured: the billing table could not be read. |
| The full run of 5,152 sentences | 3f | About 3.4 times one trial run, because 5,152 ÷ 1,500 = 3.4: about $25.60 with the preferred candidate, about $2.40 with the second |
| The search endpoint | From step 4 until the demo is recorded | Billed by the hour for as long as it exists. The rate has not been looked up. |
| Answering the test questions | Steps 6, 7, 8 | 98 questions, two approaches, a few model calls each |
| The judge | Steps 6, 8, 9 | One call per "why" answer. There are 20 "why" questions. |
| Serving the two approaches, and the chat page | Steps 10 to 12 | Not looked up |
| The monthly budget alert | Exists | Set on 2026-09-19 |

## Appendix A — names and specifics

The body of this document refers to models by role. This appendix holds the names.

| Thing | Name |
|---|---|
| Platform | Azure Databricks, East US region |
| Workspace | `db-ws-juno`, at `https://adb-7405616821600861.1.azuredatabricks.net` |
| Profile for the command-line tool | `JUNO`. The profile `DEFAULT` points at an older course workspace and is never used for this project. |
| Catalog, schema, volume | `juno`, `restaurant`, `raw` |
| Database engine for queries | `Serverless Starter Warehouse` |
| Search endpoint | `juno-vs` (does not exist yet) |
| Tagger model, preferred candidate | Claude Opus 4.8 (`databricks-claude-opus-4-8`) |
| Tagger model, second candidate | Llama 3.3 70B Instruct (`databricks-meta-llama-3-3-70b-instruct`) |
| Tagger model for the three attempts of 2026-09-20, no longer a candidate | gpt-oss-120b (`databricks-gpt-oss-120b`) |
| Agent model | Claude Sonnet 5 (`databricks-claude-sonnet-5`) |
| Judge model | Claude Opus 5 (`databricks-claude-opus-5`) |
| Embedding model | GTE Large, English (`databricks-gte-large-en`) |
| The platform's bulk function | The database function `ai_query`, run over a table |
| The platform's connector for LangGraph | The package `databricks-langchain` |
| MLflow's agent shape for deployment | `ResponsesAgent` |
| MLflow's evaluation function, used in step 9 only | `mlflow.genai.evaluate()`. It needs no approach to call when the saved answers are supplied with the questions. |
| Jobs that exist | `juno-data`, `juno-evalset`, `juno-tagging`. In the development setting each name carries a personal prefix. |
| Published prices, read on 2026-09-20 from the platform's public price pages | In the platform's billing units per million tokens: Claude Opus 4.8, 71.429 in and 357.143 out; Llama 3.3 70B Instruct, 7.143 in and 21.429 out; gpt-oss-120b, 2.143 in and 8.571 out. The pages do not give the dollar price of a unit. $0.07 is assumed, because it turns every figure into a round number: $5.00 and $25.00, $0.50 and $1.50, $0.15 and $0.60. So the preferred candidate costs ten times the second for each token read. The same pages show a separate hourly rate for bulk use (178.571, 85.714 and 71.429 units an hour). Which of the two this workspace is billed on is not known without the billing table. |
| Where the model names are set | `databricks.yml` holds one setting per role: `tagging_model`, `agent_model`, `judge_model`, `embedding_model`. `src/juno/config.py` reads the same four. Changing a model means changing a setting, not code. |

`docs/design.md` Appendix A holds the documentation's bulk list, what this workspace actually accepts,
the platform's exact messages, and how the two candidates were chosen.
