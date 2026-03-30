# /// script
# dependencies = ["httpx>=0.27"]
# requires-python = ">=3.12"
# ///
"""Sync promoted traces from MLflow datasets to local benchmark JSONL files.

Reads all MLflow dataset runs tagged with source='auto-promote',
groups by dataset name (domain.task), and writes consolidated JSONL files
to data/benchmarks/.

Idempotent: overwrites target JSONL with the union of existing manual cases
and promoted cases (deduped by input hash).

Usage:
    uv run scripts/promote.py                # sync all promoted datasets
    uv run scripts/promote.py --list         # list promoted datasets without syncing
    uv run scripts/promote.py --dataset coder.review  # sync specific dataset only
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

PROJECT_DIR = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = PROJECT_DIR / "data" / "benchmarks"

# n8n webhook base (host-side, not container-side)
N8N_BASE = "http://localhost:5678/webhook"


def input_hash(text: str) -> str:
    """Deterministic hash for dedup."""
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


def list_datasets(client: httpx.Client) -> list[dict]:
    """Fetch all datasets from MLflow via n8n."""
    resp = client.post(f"{N8N_BASE}/datasets", json={"action": "list", "limit": 200}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("datasets", [])


def get_dataset_rows(client: httpx.Client, run_id: str) -> list[dict]:
    """Fetch rows from a dataset run."""
    resp = client.post(f"{N8N_BASE}/datasets", json={"action": "get", "run_id": run_id}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("rows", [])


def load_existing_cases(path: Path) -> dict[str, dict]:
    """Load existing JSONL cases, keyed by input hash."""
    cases: dict[str, dict] = {}
    if not path.exists():
        return cases
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            case = json.loads(line)
            h = input_hash(case.get("input", ""))
            cases[h] = case
        except json.JSONDecodeError:
            continue
    return cases


def write_cases(path: Path, cases: dict[str, dict]) -> int:
    """Write cases dict to JSONL, sorted by input hash for stability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_cases = sorted(cases.values(), key=lambda c: input_hash(c.get("input", "")))
    with open(path, "w") as f:
        for case in sorted_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    return len(sorted_cases)


def sync_dataset(client: httpx.Client, name: str, datasets: list[dict]) -> tuple[int, int]:
    """Sync a single dataset name to local JSONL. Returns (total, new) counts."""
    # Find all runs matching this dataset name
    matching = [d for d in datasets if d.get("name") == name]
    if not matching:
        return 0, 0

    # Load existing local cases
    jsonl_path = BENCHMARKS_DIR / f"{name}.jsonl"
    existing = load_existing_cases(jsonl_path)
    before_count = len(existing)

    # Fetch and merge promoted cases from all matching dataset runs
    for ds in matching:
        rows = get_dataset_rows(client, ds["run_id"])
        for row in rows:
            if not row.get("input"):
                continue
            h = input_hash(row["input"])
            # Don't overwrite existing manual cases (they're higher quality)
            if h not in existing:
                existing[h] = row

    total = write_cases(jsonl_path, existing)
    new_count = total - before_count
    return total, new_count


def main() -> None:
    global N8N_BASE
    parser = argparse.ArgumentParser(description="Sync promoted traces to benchmark JSONL")
    parser.add_argument("--list", action="store_true", help="List datasets without syncing")
    parser.add_argument("--dataset", help="Sync specific dataset only (e.g. coder.review)")
    parser.add_argument("--n8n-url", default=N8N_BASE, help="n8n webhook base URL")
    args = parser.parse_args()

    N8N_BASE = args.n8n_url

    client = httpx.Client()

    try:
        datasets = list_datasets(client)
    except Exception as e:
        print(f"Failed to list datasets: {e}", file=sys.stderr)
        print("Is the stack running? (task dev)", file=sys.stderr)
        sys.exit(1)

    if not datasets:
        print("No datasets found in MLflow.")
        return

    if args.list:
        print(f"{'Name':30s} {'Rows':>6s} {'Created':>20s}")
        print("-" * 60)
        for ds in sorted(datasets, key=lambda d: d.get("name", "")):
            from datetime import datetime, timezone
            ts = ds.get("created_at", 0)
            created = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "?"
            print(f"{ds.get('name', '?'):30s} {ds.get('row_count', 0):>6d} {created:>20s}")
        return

    # Group datasets by name
    names = sorted(set(d.get("name", "") for d in datasets if d.get("name")))
    if args.dataset:
        names = [n for n in names if n == args.dataset]
        if not names:
            print(f"Dataset '{args.dataset}' not found. Available: {', '.join(sorted(set(d.get('name', '') for d in datasets)))}")
            sys.exit(1)

    print(f"Syncing {len(names)} dataset(s) to {BENCHMARKS_DIR}/")
    total_new = 0
    for name in names:
        total, new = sync_dataset(client, name, datasets)
        status = f"+{new} new" if new > 0 else "up to date"
        print(f"  {name:30s} {total:>4d} cases ({status})")
        total_new += new

    print(f"\nDone. {total_new} new cases synced.")


if __name__ == "__main__":
    main()
