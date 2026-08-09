#!/usr/bin/env python3
"""
shade/provenance.py

Captures a small, honest provenance snapshot (git commit, package
versions, timestamp) to embed in generated benchmark/diagnostic reports,
so a number in docs/benchmark.md or a paper draft can be traced back to
the exact code state and environment that produced it -- not just the
command line, which is already documented per-report, but the state of
the repository at the moment the command ran.

SCOPE, DELIBERATELY NARROW: this is wired into the diagnostic/benchmark
reports (shade/eval_harness.py's easy and hard tiers,
scripts/run_extended_benchmark.py) where a specific number is the whole
point of the report. It is NOT added to the core pipeline's default
output files (output/synthetic_usage.csv, output/governance_report.json,
etc.) -- those have an established, documented output contract this
project has repeatedly been careful not to silently grow (see ADR
0002-0004's shared reasoning for opt-in-by-default extension stages).
Adding a new field to every core pipeline JSON file on every default run
would be exactly that kind of silent contract growth; the benchmark
reports don't have the same stability expectation and directly benefit
from this instead.

Everything here degrades gracefully (returns None for a field rather than
raising) if git isn't available, the repo isn't a git checkout (e.g. a
downloaded zip rather than a clone), or a package isn't installed -- a
report should still be generated even if provenance can't be fully
captured, just with honestly-incomplete provenance rather than a crash.
"""
import subprocess
import sys
from datetime import datetime, timezone

# Packages this project actually depends on (see requirements.txt) --
# hardcoded here rather than parsed from requirements.txt at runtime so
# provenance capture has no dependency on that file's exact formatting.
TRACKED_PACKAGES = ["faker", "pandas", "numpy", "matplotlib", "pyyaml"]


def _run_git(args):
    """Runs a git command, returns stripped stdout or None on any failure
    (not a git repo, git not installed, command failed, etc.) -- provenance
    capture should never be the reason a report fails to generate."""
    try:
        result = subprocess.run(
            ["git"] + args, capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def _package_versions():
    versions = {}
    try:
        import importlib.metadata as importlib_metadata
    except ImportError:
        return {pkg: None for pkg in TRACKED_PACKAGES}
    for pkg in TRACKED_PACKAGES:
        try:
            versions[pkg] = importlib_metadata.version(pkg)
        except Exception:
            versions[pkg] = None
    return versions


def get_provenance():
    """
    Returns a dict:
      git_commit_full, git_commit_short: this checkout's HEAD, or None if
        not a git repo / git unavailable.
      git_dirty: True if there are uncommitted changes to tracked files at
        capture time (git status --porcelain non-empty), None if this
        couldn't be determined. A report generated from a dirty working
        tree is still reproducible in spirit but not by commit hash alone
        -- this field makes that visible rather than silent.
      python_version: sys.version, full interpreter version string.
      package_versions: dict of this project's actual dependencies (see
        TRACKED_PACKAGES) to their installed version, or None per-package
        if not resolvable.
      generated_at_utc: ISO-8601 UTC timestamp of capture.
    """
    commit_full = _run_git(["rev-parse", "HEAD"])
    commit_short = _run_git(["rev-parse", "--short", "HEAD"])
    status = _run_git(["status", "--porcelain"])
    dirty = None if status is None else (len(status) > 0)

    return {
        "git_commit_full": commit_full,
        "git_commit_short": commit_short,
        "git_dirty": dirty,
        "python_version": sys.version.split()[0],
        "package_versions": _package_versions(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
