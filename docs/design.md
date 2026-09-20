# Design — tagging validation and how Juno is measured

Extends the submitted design document (`design-doc.pdf`) with decisions taken during the build.
Nothing here contradicts the submission; it makes two things concrete: how `review_facts` is proved
fit to count, and how Juno's score is separated from the tagger's.

## 1. The problem this solves

Juno counts rows in `review_facts`, which an LLM produces. So a single count-accuracy number mixes
two different failures:

| Failure | Example |
|---|---|
| The tagger mislabels sentences | Finds 400 of 466 service complaints |
| The agent mishandles its own result | SQL returns 466, the answer says "about 500" |

Reported as one number, "Juno is 85% accurate" cannot be defended. The design below separates them
and refuses to build on tags that are not good enough.

## 2. Order of work

```
build review_facts ──▶ validate it ──▶ gate ──▶ build Juno
                            │                      │
                            └── fails ─────────────┘
                                iterate prompt or model
```

Juno is not built until the gate passes, or until the gate is deliberately lowered with the
measurement as evidence.

## 3. What is measured, and on what

| Measure | Definition | Purpose |
|---|---|---|
| **Row F1** | Per category, over (sentence, category, sentiment) triples | Did the tagger label the right sentences? |
| **Count error** | `(llm_n - human_n) / human_n` per (category, sentiment) | The error Juno actually inherits |
| **Agent accuracy** | Juno's counting run against `human_labels`, dev split only | Juno with a perfect tagger |
| **System accuracy** | Juno's counting run against `review_facts` | The headline number |

Row F1 and count error are different. Misses and false positives can cancel, giving a good count from
bad rows — so both are required, and neither alone is sufficient.

## 4. The gate

Juno's target is *within 10% on at least 80% of count questions*. The tagger must clear that itself,
or the target is unreachable whatever the agent does.

| Check | Threshold | Measured on |
|---|---|---|
| Macro-F1 across the 12 categories | ≥ 0.60 | The whole sample |
| Count error within 10% | ≥ 80% of pairs | **Only pairs with ≥ 30 sentences in the sample** |

**Why the support restriction.** Eval questions use (category, sentiment) pairs with ≥ 30 sentences in
the full corpus. In a 500-sentence sample those pairs hold 1–4 sentences, where one extra tag reads as
+25% to +100%. That is sampling noise, not tagger error. Pairs below the floor are still reported, and
every pair is checked again on the full corpus.

**If the gate cannot be passed** after three prompt or model rounds, stop and choose explicitly:

1. Accept the ceiling, lower Juno's count target to what the tagger supports, and report the
   measurement as the reason; or
2. Narrow the claim to the categories that do pass, and report the rest as a limitation.

Either way the decision and its evidence go in the log and the README. Silently proceeding is not an
option.

## 5. Constraints found during the build

- **Claude endpoints cannot be used for tagging.** `ai_query` batch inference rejects them:
  `Endpoint databricks-claude-sonnet-5 is not supported for batch inference`. Tagger candidates are
  the open models: `databricks-gpt-oss-120b`, `databricks-meta-llama-3-3-70b-instruct`,
  `databricks-llama-4-maverick`, `databricks-qwen35-122b-a10b`.
  Claude remains available for the agent and the judge, which call endpoints directly.
- **Three models, three roles**, unchanged otherwise: tagger (batch, cheap), agent
  (`databricks-claude-sonnet-5`), judge (`databricks-claude-opus-5`, deliberately different from the
  agent).

## 6. Prompt discipline

- The prompt lives in `src/juno/tagging.py`, versioned, with the reason for each revision.
- **No dataset sentences in the prompt.** Examples are hand-written; a real labelled sentence would
  leak ground truth into the answering path.
- Iteration happens on the sample only. The full corpus is tagged once, with the chosen prompt.

## 7. Measurements so far

500 sentences, `databricks-gpt-oss-120b`, gate = 0.60 macro-F1 and 80% of pairs within 10%.

| Round | Change | Macro-F1 | Pairs within 10% (unrestricted) |
|---|---|---|---|
| v1 | Category list only | 0.51 | 20% |
| v2 | Added category boundaries and counter-examples | 0.53 | 30% |
| v3 | Rebalanced: label every topic explicitly evaluated | **0.59** | 35% |

Errors by round:

- **v1 over-tagged** secondary categories: Drinks#Style_Options +350%, Food#Style_Options +127%,
  while under-tagging Restaurant#General by 31%.
- **v2 overcorrected** — "most sentences cover one topic" caused under-tagging:
  Restaurant#General NEG −46%, Service#General POS −23%.
- **v3** holds the boundaries without suppressing multi-topic sentences. Large categories are strong
  (Food#Quality 0.83, Service#General 0.84); small ones remain weak (Restaurant#Miscellaneous 0.09,
  Location#General 0.27).

The pattern is consistent: **the tagger is good where there is data and poor where there is not.**
That is worth reporting as a finding, since it is exactly where the retrieval baseline is weakest too.

## 8. Reporting

The results table presents three numbers, not one:

```
agent accuracy    (over human_labels, dev split, diagnostic)
system accuracy   (over review_facts — the headline)
difference        = the cost of imperfect tagging
```

Rules that keep this honest:

- The oracle diagnostic runs on **dev only**, never the frozen test split.
- It is labelled a diagnostic everywhere it appears.
- The A vs B comparison stays system against system. Comparing A's end-to-end score with B's oracle
  score would be meaningless.

## 9. Open decisions

1. **Which tagger model.** v3 prompt on gpt-oss-120b reaches 0.59. A second candidate should be
   measured on the same sample before committing.
2. **Sample size for the gate.** 500 gives noisy count errors for small pairs. 1,500–2,000 would make
   the count check meaningful for more pairs, at roughly three times the sample cost (still cents).
3. **What happens if no model passes.** Option 1 or 2 from section 4 — to be chosen with the numbers
   in hand, not in advance.
