# Reference environment for exactly reproducing the SHADE pipeline output.
# Build:  docker build -t shade .
# Run:    docker run --rm -v "$(pwd)/output:/app/output" shade
# (mounting ./output lets you inspect the generated CSVs/JSON/dashboard.png
# on the host after the container exits)
#
# This image runs entirely offline against synthetic (Faker-generated)
# data -- no network calls, no real organizational data, consistent with
# the paper's Data availability statement.
FROM python:3.11-slim

WORKDIR /app

# Install pinned dependencies first so this layer is cached across code
# changes that don't touch requirements.txt.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the formal-verification + evaluation-harness checks by default so a
# failed build/run surfaces regressions immediately; override the command
# to run the full pipeline instead, e.g.:
#   docker run --rm shade python3 shade/run_pipeline.py --n 2000
# Or run the slower, opt-in extended benchmark (DLP at higher volume and
# across more seeds, the three opt-in pipeline extensions under load at
# n=5000 -- see docs/benchmark.md's "Scale check" section and
# scripts/run_extended_benchmark.py's docstring for why this is separate
# from the fast default check above):
#   docker run --rm -v "$(pwd)/experiments/output:/app/experiments/output" shade python3 scripts/run_extended_benchmark.py
CMD ["python3", "tests/test_pipeline.py"]
