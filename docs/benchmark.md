# Benchmark scope and results

This document states plainly what `shade/eval_harness.py` and `shade/verify_policy.py`
measure and, more importantly, what they do not.

## What is measured

**DLP redaction (`shade/eval_harness.py`).** Precision, recall, and F1 of the
four regex patterns in `shade/dlp_redact.py` (email, phone, SSN-shaped,
fake-API-key-shaped) against a purpose-built synthetic benchmark set of
300 samples (fixed seed 42, reproducible). The benchmark set is generated
by `shade/eval_harness.py` itself, independently of `shade/generate_synthetic_data.py`,
and includes: structural variants of each true-positive pattern (different
email/phone formatting conventions, different API-key-length examples),
deliberate near-miss distractors that should NOT match a look-alike pattern
(order numbers, zip+4 codes, undashed digit strings, mismatched key
prefixes), and clean filler text with no pattern present at all.

Current result at n=300, seed=42: micro-averaged precision, recall, and F1
are all 1.0, with zero false positives or false negatives across all four
pattern types (see `experiments/output/dlp_benchmark_report.json` after
running `python3 shade/eval_harness.py`).

**How much should a perfect score be trusted?** A point estimate alone
doesn't say -- 0 errors in 10 samples and 0 errors in 10,000 samples are
very different claims, and a bare "F1 = 1.0" doesn't distinguish them.
`shade/eval_harness.py` now reports a 95% Wilson score interval for
precision and recall (the standard interval for a binomial proportion,
chosen specifically because it stays well-behaved at the 0%/100%
boundary these benchmarks tend to land on) alongside every point
estimate. At n=300, seed=42, the micro-averaged precision/recall interval
is **[0.978, 1.0]** -- meaning the data are consistent with a true error
rate as high as roughly 2.2%, not just with "zero, forever." At n=5,000
(see the Scale check below), that interval tightens to **[0.999, 1.0]**.
This is the honest way to read every "F1 = 1.0" in this document: as a
point estimate with a stated, sample-size-dependent margin, not as a
claim of provably-zero error.

F1 itself is a nonlinear function of precision and recall with no simple
closed-form interval, so it's estimated by nonparametric bootstrap
(resampling the scored items with replacement, 1,000 resamples, fixed
seed). This has a real limitation worth stating rather than hiding: when
the observed sample has zero errors, every bootstrap resample is also
error-free, so the bootstrap interval **degenerates to exactly [1.0,
1.0]** -- which looks like perfect certainty but is actually an artifact
of resampling from an error-free sample, not evidence that the true rate
is exactly 1.0. `shade/eval_harness.py` reports a second interval,
`f1_ci_95_wilson_plugin` (F1's formula evaluated at the Wilson bounds of
precision and recall), specifically to give a non-degenerate answer in
this case -- conservative, since it ignores the correlation between
precision's and recall's estimation errors, but genuinely informative
where the bootstrap interval isn't. See `shade/eval_harness.py`'s
docstring and `tests/test_pipeline.py`'s
`test_dlp_bootstrap_f1_ci_degenerates_but_wilson_plugin_does_not` for the
full reasoning -- that test exists specifically so this behavior stays
documented and intentional rather than silently "fixed" (i.e. hidden) by
a future change.

**Multi-seed check.** Since a single seed could in principle be a lucky
draw rather than a representative one, the same benchmark was regenerated
and rescored at five different seeds (42, 1, 7, 99, 12345; 300 samples
each). All five produced micro-averaged precision/recall/F1 of 1.0 with
zero false positives or false negatives across all four pattern types
(verified on the maintainer's own machine, independent of the sandbox
this harness was originally developed in -- see `docker run --rm shade
python3 shade/eval_harness.py --seed <N>` to reproduce, or run natively with
`for s in 1 7 99 12345; do python3 shade/eval_harness.py --n 300 --seed $s;
done`). This rules out "seed=42 happened to be favorable" as an
explanation for the result; it does NOT rule out the scope limitation
below, which is a property of what the benchmark tests for, not which
seed generated it.

**A perfect score here is a statement about this benchmark's current
scope, not a claim that the regexes are robust in general.** The benchmark
set currently covers clean structural variation (spacing, punctuation,
common format conventions) but does not yet include: OCR noise or
transcription errors, Unicode homoglyphs or lookalike characters,
non-US phone/SSN-equivalent formats, deliberately obfuscated PII
(e.g. "j a n e dot doe at example dot com"), or adversarial input designed
to evade regex matching. Those are natural next benchmark tiers (see
"Future work" below) and would very plausibly surface recall gaps that
this version of the harness cannot detect, since it wasn't designed to.

**Governance decision matrix (`shade/verify_policy.py`).** Formal, exhaustive
verification (not a precision/recall metric) that the 3x3 decision table
is complete and non-conflicting -- see
`docs/adr/0001-formal-verification-of-governance-matrix.md` for why this
is the right tool for a 9-cell table and not something a P/R/F1 framing
even applies to (it is a deterministic total function, not a classifier
making predictions against ground truth).

## What is NOT measured

- **Real-world DLP detection accuracy.** The benchmark's ground truth is
  synthetic and programmatically assigned by the same code that generates
  the samples. This is internal consistency ("does the detector do what
  the benchmark's construction implies it should do"), not an estimate of
  how the regexes would perform against real, messy, adversarial, or
  domain-specific text. The paper's Data availability statement is
  correct that no real data is used anywhere in this repository, including
  in this harness.
- **Discovery accuracy.** `shade/discovery_scan.py` reads a pre-generated
  ground-truth sanctioned/unsanctioned label rather than performing
  independent detection (network telemetry, endpoint agents), so scoring
  it against that same label would be circular and is not attempted.
- **Governance-outcome "correctness" in a policy sense.** Formal
  verification confirms the matrix is complete and internally consistent;
  it says nothing about whether BLOCK-vs-ALLOW-vs-REDACT is the *right*
  policy choice for a given cell. That is a governance design question,
  not something code can validate.
- **Anything about production tooling.** The README's "Production tooling"
  table already states SHADE's modules are illustrative re-implementations
  of the pattern used by cited production tools (aidlp/llmproxy, Presidio,
  GovLLM, etc.), not benchmarks of those tools themselves.

## Reproducing these numbers

```bash
python3 shade/eval_harness.py --n 300 --seed 42 --out experiments/output/dlp_benchmark_report.json
python3 shade/verify_policy.py
python3 tests/test_pipeline.py   # runs both as part of CI-equivalent checks, with threshold assertions
```

The command above includes confidence intervals by default
(`--n_bootstrap 1000`); increase or decrease that flag to trade off
bootstrap runtime against how finely the F1 interval's percentiles are
estimated -- it has no effect on the Wilson intervals, which are a closed
form, not a resampling estimate.

`experiments/dlp_benchmark_config.json` records the parameters (n, seed,
F1 thresholds) used in CI so a future contributor can see at a glance what
"passing" means without reading the harness source.

## Scale check (2026-08-09)

The n=300 benchmark above is what CI runs on every push (fast, cheap).
As a separate, one-off check (not part of CI, since it's slower and adds
nothing CI's smaller run doesn't already establish about *correctness* --
only about *scale*), the same benchmark was re-run at higher volumes:

| n | seed | precision | recall | f1 | 95% CI (precision/recall) | fp | fn |
|---|---|---|---|---|---|---|---|
| 300 (CI default) | 42 | 1.0 | 1.0 | 1.0 | [0.978, 1.0] | 0 | 0 |
| 2,000 | 42 | 1.0 | 1.0 | 1.0 | [0.997, 1.0] | 0 | 0 |
| 10,000 | 42 | 1.0 | 1.0 | 1.0 | [0.999, 1.0] | 0 | 0 |

The interval tightens monotonically as n grows -- exactly what Wilson's
interval should do for a fixed (perfect) observed result, and a useful
sanity check that the interval computation itself isn't just returning a
fixed width. See `tests/test_pipeline.py`'s
`test_dlp_confidence_intervals_tighten_with_more_samples` for the
regression test encoding this.

The multi-seed check was also extended to two more seeds (2026, 555) at
n=1,000 each, beyond the five seeds already documented above at n=300:

| seed | n | precision | recall | f1 |
|---|---|---|---|---|
| 1 | 1,000 | 1.0 | 1.0 | 1.0 |
| 7 | 1,000 | 1.0 | 1.0 | 1.0 |
| 99 | 1,000 | 1.0 | 1.0 | 1.0 |
| 12345 | 1,000 | 1.0 | 1.0 | 1.0 |
| 2026 | 1,000 | 1.0 | 1.0 | 1.0 |
| 555 | 1,000 | 1.0 | 1.0 | 1.0 |

Same conclusion as before, now at higher volume and across more seeds:
this rules out both "seed=42 was lucky" and "300 samples was too small to
surface a gap" as explanations for the perfect score. It does not narrow
the scope limitation already stated above -- the benchmark still only
covers clean structural variation, not OCR noise, homoglyphs,
international formats, or adversarial obfuscation. More samples of the
same kind of input will keep scoring 1.0; that was never in question.

**The three opt-in pipeline extensions were also stress-tested at scale**
(n=5,000, well above the n=100-200 used during their original integration
verification in ADRs 0002-0004):

- `--propose_policy_review`: completes in ~2.8s, still returns
  `CANDIDATE_PENDING_HUMAN_REVIEW` with zero formal-verification
  violations.
- `--include_mcp_monitoring`: completes in ~4.2s, generates 5,000
  synthetic tool-call rows with a governance-action distribution
  consistent with `MCP_DECISION_MATRIX` (e.g. no `execute`+`critical`
  calls slip through as anything but `BLOCK`).
- `--privatize_governance_report`: completes in ~2.4s. One finding worth
  noting explicitly: **absolute MAE does not shrink with n, but relative
  error does.** At epsilon=1.0, seed=42, the action-distribution MAE was
  1.2 at both n=500 and n=5,000 -- identical, because the Laplace
  mechanism's noise scale (`sensitivity/epsilon`) depends only on
  epsilon, not on how large the counts being noised are. But relative to
  the true counts, that same fixed absolute error is far less
  significant at scale: MAE/mean-count was 0.012 (1.2%) at n=500 versus
  0.0012 (0.12%) at n=5,000 -- a 10x improvement in relative utility for
  a 10x increase in dataset size, exactly as differential privacy theory
  predicts (fixed absolute noise, shrinking relative impact as the
  signal being protected grows). This is a real, measured property of
  the implementation, not an assumption -- see
  `docs/adr/0004-integrating-dp-aggregate-reporting.md` for the
  integration this measures.
- All three flags run together (n=5,000) completed in ~4.1s with no
  errors, produced all 12 expected output files, and the full
  `tests/test_pipeline.py` suite (16 checks) still passed afterward.

Reproduce with a single command (see `scripts/run_extended_benchmark.py`,
which runs exactly the checks above plus a re-run of the fast
`tests/test_pipeline.py` suite afterward, and writes a structured JSON
report):

```bash
python3 scripts/run_extended_benchmark.py
```

Or inside Docker, for an environment-independent run:

```bash
docker build -t shade .
docker run --rm -v "$(pwd)/experiments/output:/app/experiments/output" shade python3 scripts/run_extended_benchmark.py
```

This is also available as a manually-triggered GitHub Actions job
(`extended-benchmark` in `.github/workflows/test.yml` -- Actions tab ->
"SHADE self-check" -> "Run workflow"), so anyone with a fork or PR access
can reproduce these numbers without a local Python environment at all;
the report is uploaded as a downloadable CI artifact. It is deliberately
NOT run on every push/PR (unlike the fast `test` job) since it is slower
and checks a different property (scale, not correctness) -- see the
script's own docstring for the full reasoning.

The individual commands, if you want to run just one piece rather than
the whole script:

```bash
python3 shade/eval_harness.py --n 2000 --seed 42
python3 shade/eval_harness.py --n 10000 --seed 42
for s in 1 7 99 12345 2026 555; do python3 shade/eval_harness.py --n 1000 --seed $s; done
python3 shade/run_pipeline.py --n 5000 --propose_policy_review --include_mcp_monitoring --privatize_governance_report
python3 shade/dp_aggregate_reporting.py --n 500 --epsilons 1.0
python3 shade/dp_aggregate_reporting.py --n 5000 --epsilons 1.0
```

## Harder benchmark tier: measured results (2026-08-09)

The "Future work" item that used to sit here -- OCR noise, Unicode
homoglyphs, international formats, deliberate obfuscation -- has been
built and measured (`shade/eval_harness.py --tier hard`,
`build_hard_benchmark_dataset()` / `score_hard_tier()`). Unlike the
n=300 default benchmark, this tier is a small, hand-curated, FIXED set
(18 fragments, not randomly generated -- there's no larger population to
sample from, so no bootstrap CI is computed for it, only a Wilson
interval per category on the observed counts) and is diagnostic, not a
CI pass/fail gate: a low recall here is the expected, honest result for
a regex-only detector authored against clean, US-centric examples, not a
regression.

**Overall recall: 0.222 [Wilson 95% CI: 0.09, 0.452]** -- roughly one in
five of these harder true-positive fragments is caught by the existing
four patterns. By category:

| Category | Recall | 95% CI | n |
|---|---|---|---|
| `fullwidth_digit` | 1.0 | [0.342, 1.0] | 2 |
| `unicode_homoglyph` | 0.333 | [0.061, 0.792] | 3 |
| `ocr_noise` | 0.2 | [0.036, 0.624] | 5 |
| `obfuscated` | 0.0 | [0.0, 0.434] | 5 |
| `international_format` | 0.0 | [0.0, 0.561] | 3 |

**Every category's expected outcome was empirically checked against the
actual patterns before being included** (measured, not assumed), and two
results were genuinely non-obvious going in:

- **Fullwidth Unicode digits are fully caught (2/2), not missed.**
  Python's `\d` in default (Unicode) mode matches Unicode decimal-digit
  characters, not just ASCII 0-9, so `５５５-１２３-４５６７` matches
  the phone pattern exactly as written. This is a positive finding
  reported alongside the negative ones specifically so the write-up
  doesn't only showcase failures.
- **A Unicode homoglyph in an email's local part is sometimes still
  caught (1/3 in this category), depending on exactly where it falls.**
  A homoglyph in the domain is never caught (the domain character-class
  run breaks with no fallback). A homoglyph in the local part IS caught
  if a punctuation character (a genuine word/non-word regex boundary)
  follows it before the rest of the address -- the regex finds a valid
  match starting from that punctuation boundary. A homoglyph immediately
  followed by more letters, with no intervening punctuation, is not
  caught. This nuance would have been easy to get wrong by assuming
  "homoglyphs always defeat the pattern" or "never defeat it" -- neither
  is true, which is exactly why this was tested rather than assumed.
- **OCR noise does not affect the API key pattern the way it affects
  phone/SSN.** `fake_api_key`'s character class (`[A-Za-z0-9_-]`) already
  accepts both a digit and its common OCR look-alike letter (e.g. `0` and
  `O`), so a single-character OCR-style substitution doesn't actually
  change whether the pattern matches. Phone and SSN use `\d`-only
  positions in fixed locations, so the same class of substitution does
  break them. This is a property of how permissive a pattern's character
  class is, not of "OCR noise" as a single uniform threat.
- **Obfuscation (spelled-out or heavily spaced PII) and international
  formats are caught 0% of the time**, exactly as the patterns' known
  scope (US-centric, fixed-shape, non-obfuscated) predicts. This
  confirms rather than surprises -- included for completeness of the
  measured record, not because the result was in doubt.

**What this does and doesn't mean:** these are real, measured recall
gaps in `shade/dlp_redact.py`'s four regex patterns against a small,
specific set of harder true positives -- not an estimate of real-world
detection accuracy (see "What is NOT measured" above, which applies here
too), and not a claim that 22% is "the" hard-tier accuracy of DLP
regexes in general (the fixed set is illustrative, not a random sample
of the space of possible obfuscation techniques). What it does establish
concretely: the boundary this project has described qualitatively since
early drafts of this document ("does not yet include OCR noise... would
very plausibly surface recall gaps") is now a measured boundary with
specific numbers behind it, not just a stated caveat.

Reproduce with:

```bash
python3 shade/eval_harness.py --tier hard --out experiments/output/dlp_hard_tier_report.json
```

`tests/test_pipeline.py`'s `test_dlp_hard_tier_is_diagnostic_and_genuinely_harder`
asserts the OPPOSITE of every other test in this suite: that overall
recall stays below 1.0, specifically to catch the case where this tier
accidentally stopped being hard (e.g. a fragment edited into something
the patterns already handle) without anyone noticing.

## Future work (not implemented here)

- If these regex recall gaps matter for a given deployment, evaluating
  whether an ML-based recognizer (e.g. Presidio/spaCy, as the production
  tools cited in the README already use) closes them -- measured, not
  assumed, per the existing caveat in `shade/dlp_redact.py`'s docstring.
  The hard tier above is exactly the kind of benchmark that evaluation
  would need to be run against to claim an improvement, not just a
  restatement of the n=300 easy-tier F1.
- Expanding the hard tier's international-format coverage beyond the
  three formats currently included (UK/India phone, UK National
  Insurance number) if a specific jurisdiction becomes relevant to a
  future extension of this work.
