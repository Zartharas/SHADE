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

`experiments/dlp_benchmark_config.json` records the parameters (n, seed,
F1 thresholds) used in CI so a future contributor can see at a glance what
"passing" means without reading the harness source.

## Future work (not implemented here)

- Harder benchmark tiers: OCR noise, Unicode homoglyphs, international PII
  formats, adversarial/obfuscated input.
- If regex recall gaps are found on harder tiers, evaluating whether an
  ML-based recognizer (e.g. Presidio/spaCy, as the production tools cited
  in the README already use) closes them -- measured, not assumed, per the
  existing caveat in `shade/dlp_redact.py`'s docstring.
