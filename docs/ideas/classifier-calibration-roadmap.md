# Classifier Calibration Roadmap

Post-first-iteration plan for continued calibration of Sentinel's military threat classifier.

**Current state:** 50 human-labeled articles, 10 calibration rules in system prompt, action-tier accuracy at 98%.

---

## Next Steps (Ordered by Impact)

### 1. Build a proper hold-out set (immediate)

Split the 50 labeled articles into two pools:
- **Development set (35 articles):** Used for prompt iteration and error analysis.
- **Hold-out set (15 articles):** Never used for iteration. Only run after a prompt change to confirm real improvement vs overfitting to the dev set.

Going forward, every new batch of labels should be split 70/30 the same way. The hold-out tells you whether gains on the dev set translate to real improvement.

**Why this matters:** Multiple 2025-2026 practitioner guides (Galileo, Evidently AI, tianpan.co) document "eval set rot" -- teams iterate on a fixed set, overfit the prompt to it, then ship regressions to production. A blind hold-out is the cheapest insurance.

### 2. Error analysis on production disagreements (this week)

Run the current classifier on the last 7 days of production articles. Manually review:
- All articles scored urgency 5+ (potential action-tier triggers)
- A random sample of 10-15 articles scored 1-3 (check for missed threats)

Focus on **disagreements** -- cases where your gut says the classifier got it wrong. These become the next round of ground-truth labels AND reveal which rules need tightening.

### 3. Grow the labeled set to 100-150 via targeted sampling (next 2-4 weeks)

Do NOT label randomly. Use an active learning approach:

**Priority 1 -- Boundary cases (highest value):**
- Articles the classifier scored 4-6 (the uncertain middle zone between "ignore" and "act")
- Articles where the classifier's reasoning mentions hedging ("possibly", "unclear if")

**Priority 2 -- Failure modes from error analysis:**
- Any pattern you spotted in Step 2 -- find more articles like those

**Priority 3 -- Diversity coverage:**
- At least 2-3 examples per source language (PL/EN/UA/RU)
- At least 2-3 examples from each source type (Telegram, RSS, GDELT)

**Why active learning beats random:** Research (ACL 2024, ActiveLLM 2026) shows uncertainty-targeted sampling achieves the same accuracy with 50-80% fewer labels than random sampling. For a single human labeler, this is the critical efficiency lever.

### 4. Add 3-5 few-shot examples to the system prompt (after reaching 100 labels)

Current system uses only rules (instructions). Research consensus (Anthropic guide, multiple 2025-2026 practitioner tests):

| Strategy | Best for |
|----------|----------|
| Rules alone | Constraint boundaries, edge-case handling, "do NOT" behaviors |
| Few-shot examples | Tone, implicit patterns, borderline judgment calls |
| Rules + examples | Best overall -- rules define the envelope, examples anchor the pattern |

**What to add:**
- 3 examples of articles that SHOULD trigger action tier (urgency 8-10) with brief reasoning
- 2 examples of articles that look scary but are NOT threats (urgency 2-4) with brief reasoning

Pick examples that demonstrate the **boundaries** -- not obvious cases. One edge case teaches more than five slam dunks. Include at least one example per language.

**Diminishing returns on examples:** Research consistently shows gains flatten after 5-8 in-context examples. With a smaller model like Haiku, fewer is better (context window competition with rules). Start with 3, measure, add 2 more only if accuracy improves.

### 5. Periodic re-calibration loop (ongoing, monthly)

The production loop from Galileo's 2026 guide:

```
1. Sample 20-30 production articles (mix of random + high-urgency)
2. Label them yourself (ground truth)
3. Compare against classifier output
4. If agreement > 90%: classifier is still calibrated, merge into dev set
5. If agreement < 90%: find disagreement patterns, update rules/examples, re-run
6. Refresh hold-out set quarterly (promote old hold-out to dev, add fresh examples)
```

This is 30-60 minutes of human time per month. The flywheel: each correction makes the next round smaller.

---

## How Many Labels Per Stage

| Stage | Labels needed | Purpose |
|-------|--------------|---------|
| Initial calibration (done) | 50 | Establish baseline rules |
| Proper split + first expansion | 100-150 | Dev/holdout split, cover failure modes |
| Mature steady-state | 200-300 total | Enough for statistical confidence (+/- 5% at 95% CI requires ~384 samples for pass/fail) |
| Monthly maintenance | 20-30/month | Drift detection, regression prevention |

You do not need thousands of labels for prompt-based calibration. The constraint is quality and coverage of edge cases, not raw volume.

---

## When Prompt Engineering Hits Diminishing Returns

Practitioners converge on "the 80% rule": good prompt engineering gets you ~80% of the way to peak. After that, each iteration costs more and yields less.

**Signals that you have hit the ceiling:**
- Last 3 prompt iterations each improved accuracy by <1%
- Remaining errors are in genuinely ambiguous cases (you as the human would also hesitate)
- Adding more rules causes regressions elsewhere (rules conflict)
- The model's reasoning is correct but its score calibration is off (e.g., it says "moderate threat" but scores 7 instead of 5)

**When to consider fine-tuning:**
- NOT yet for Sentinel. Fine-tuning thresholds from practitioner consensus:
  - Minimum 500-1000 clean labeled examples for classification
  - Minimum 7B parameter model for nuanced multi-class tasks
  - Only when prompt engineering has demonstrably plateaued AND volume justifies the cost
  - Fine-tuning a small model on <500 examples memorizes surface patterns, not generalizable logic

**For Sentinel specifically:** At current volume (~hundreds of articles/day) and with Haiku's low cost, prompt engineering is the right tool for the foreseeable future. Revisit fine-tuning only if:
1. You accumulate 500+ labeled examples AND
2. Accuracy plateaus below your target AND
3. The failure mode is something teachable (pattern-based, not reasoning-based)

---

## Active Learning -- Which Articles to Label Next

Ranked by information value:

1. **Disagreements** -- articles where classifier output != your judgment (highest value per label)
2. **Boundary zone** -- urgency 4-6 scores (the uncertain middle)
3. **High-confidence errors** -- classifier says urgency 9+ but you'd score <5, or vice versa (reveals systematic bias)
4. **New patterns** -- articles from newly added sources or in formats the classifier hasn't seen
5. **Random sample** -- 20% of your labeling budget should be random to catch unknown unknowns

**Practical implementation for Sentinel:**
- Add a field to the diagnostic output that flags articles in the 4-6 urgency band
- Periodically review the last N articles scored 8+ (check for false alarms)
- Any article that triggers action-tier in production should be retroactively verified

**Do NOT prioritize:**
- Articles scored 1-2 that are obviously noise (minimal information gain)
- Articles in well-covered patterns you already have rules for

---

## Rules vs Few-Shot Examples -- Decision Framework

```
Is the desired behavior easy to articulate as a constraint?
  YES -> Write a rule ("Never score exercises/drills above 5")
  NO  -> Is it a judgment call / implicit pattern?
    YES -> Add a few-shot example showing the boundary
    NO  -> Both (rule defines the principle, example demonstrates it)
```

**Key finding from 2025 testing (Doug Turnbull):** On smaller models, cramming too many examples after rules can cause the model to *forget* the rules. With Haiku-class models, prefer rules with strategic examples rather than example-heavy prompts.

**Current Sentinel approach (rules only) is fine until:**
- You find cases where the rule is correct but the model misapplies it
- You need to demonstrate *degree* (how much urgency does X warrant?)
- You want to anchor the scale (what does a "7" look like vs a "4"?)

---

## Hold-out Set Management

**Structure:**
```
labeled_data/
  dev_set.yaml          # 70% -- used for iteration
  holdout_set.yaml      # 30% -- never used for iteration
  production_reviews/   # monthly labeled samples
  CHANGELOG.md          # what changed when
```

**Rules:**
1. Never look at hold-out results during prompt iteration
2. Run hold-out only as a final validation after dev-set iteration converges
3. Refresh hold-out quarterly by promoting current hold-out to dev, creating new hold-out from recent production samples
4. Version everything -- tag the prompt version, the dataset version, and the results together
5. If hold-out performance drops >5% below dev-set performance, you have overfit the dev set

**Statistical note:** With 15 hold-out examples, a single error moves the score by ~7%. At 50 hold-out examples, a single error is ~2%. Target 50 hold-out examples as you grow the labeled set -- this gives meaningful signal without requiring massive labeling effort.

---

## Summary: The Calibration Flywheel

```
         [Production articles]
                |
                v
    [Sample boundary cases + random]
                |
                v
      [Human labels (you)]
          /          \
         v            v
   [Dev set]    [Hold-out set]
       |
       v
[Error analysis -> update rules/examples]
       |
       v
[Validate on hold-out]
       |
       v
[Deploy updated prompt]
       |
       v
         [Production articles] ... (repeat monthly)
```

Each cycle should take 30-60 minutes of labeling time. The goal is not perfection -- it is a monotonically improving system that never regresses on known failure modes.
