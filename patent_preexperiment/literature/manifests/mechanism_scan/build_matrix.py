"""
build_matrix.py - Build mechanism_matrix.csv from JSONL scan batches.

Hard assertions (V2.1):
  - Expected usable lit_id = ledger - duplicate(63) - damaged(108) = 106
  - All lit_id must be in ledger (<=108)
  - No unexpected IDs, no missing IDs
  - Matrix must have exactly 106 rows
  - Duplicate lit_id -> FATAL (not warning + last wins)
  - Ledger cross-verify: pub_no in scan must match ledger pub_no for same lit_id

Usage:
  python build_matrix.py
"""

import csv
import json
import os
import sys

SCAN_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_PATH = os.path.join(os.path.dirname(SCAN_DIR), 'literature_ledger.csv')
OUTPUT_PATH = os.path.join(SCAN_DIR, 'mechanism_matrix.csv')

EXPECTED_COUNT = 106
EXCLUDED_IDS = {63, 108}  # 63=duplicate, 108=damaged


def load_ledger():
    """Load ledger and return (usable_ids set, id->pub_no mapping)."""
    usable = set()
    id_pubno = {}
    with open(LEDGER_PATH, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            lid = int(float(r['lit_id']))
            if lid not in EXCLUDED_IDS:
                usable.add(lid)
                id_pubno[lid] = r.get('pub_no', '').strip()
    return usable, id_pubno


def load_all_batches(ledger_pubno):
    """Load all JSONL batches and return dict keyed by lit_id.

    V2.1: duplicate lit_id -> FATAL; pub_no cross-verify against ledger.
    """
    entries = {}
    jsonl_files = sorted(f for f in os.listdir(SCAN_DIR) if f.endswith('.jsonl'))

    for fname in jsonl_files:
        path = os.path.join(SCAN_DIR, fname)
        with open(path, encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f'JSON error in {fname}:{line_num}: {exc}', file=sys.stderr)
                    sys.exit(1)

                lid = e.get('lit_id')
                if lid is None:
                    print(f'Missing lit_id in {fname}:{line_num}', file=sys.stderr)
                    sys.exit(1)

                # Hard gate: lit_id must be a positive int <= 108
                if not isinstance(lid, int) or lid <= 0 or lid > 108:
                    print(
                        f'INVALID lit_id={lid} in {fname}:{line_num} '
                        f'(must be 1..108)',
                        file=sys.stderr,
                    )
                    sys.exit(1)

                # Skip excluded IDs
                if lid in EXCLUDED_IDS:
                    continue

                # V2.1: Duplicate lit_id -> FATAL
                if lid in entries:
                    prev_fname = entries[lid].get('_source_file', 'unknown')
                    print(
                        f'FATAL: duplicate lit_id={lid} in {fname}:{line_num} '
                        f'(previously in {prev_fname}). '
                        f'Duplicate is not allowed — fix scan source.',
                        file=sys.stderr,
                    )
                    sys.exit(1)

                # V2.1: Ledger cross-verify pub_no
                scan_pubno = e.get('pub_no', '').strip()
                ledger_pubno_val = ledger_pubno.get(lid, '').strip()
                if scan_pubno and ledger_pubno_val and scan_pubno != ledger_pubno_val:
                    print(
                        f'FATAL: lit_id={lid} pub_no mismatch in {fname}:{line_num}: '
                        f'scan="{scan_pubno}" vs ledger="{ledger_pubno_val}"',
                        file=sys.stderr,
                    )
                    sys.exit(1)

                e['_source_file'] = fname
                entries[lid] = e

    return entries


def build_matrix(entries):
    """Write CSV matrix and return row count."""
    fields = [
        'lit_id', 'doc_kind', 'pub_no',
        's_S1', 's_S2', 's_S3', 's_S4', 's_S5',
        's_chain_notes',
        'a_S1', 'a_S2', 'a_S3', 'a_S4', 'a_S5',
        'candidates',
        'b_relation', 'b_disclosed', 'b_gap',
        'c_relation', 'c_disclosed', 'c_gap',
        'd_relation', 'd_disclosed', 'd_gap',
        'f_relation', 'f_disclosed', 'f_gap',
        'crowded', 'gap_hook', 'deep_review', 'notable',
    ]

    with open(OUTPUT_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for lid in sorted(entries):
            e = entries[lid]
            sc = e.get('s_chain', {})
            ca = e.get('candidate_assessments', {})

            row = {
                'lit_id': lid,
                'doc_kind': e.get('doc_kind', ''),
                'pub_no': e.get('pub_no', ''),
                's_S1': sc.get('S1', '无'),
                's_S2': sc.get('S2', '无'),
                's_S3': sc.get('S3', '无'),
                's_S4': sc.get('S4', '无'),
                's_S5': sc.get('S5', '无'),
                's_chain_notes': e.get('s_chain_notes', ''),
                'a_S1': sc.get('S1', '无'),
                'a_S2': sc.get('S2', '无'),
                'a_S3': sc.get('S3', '无'),
                'a_S4': sc.get('S4', '无'),
                'a_S5': sc.get('S5', '无'),
                'candidates': ';'.join(e.get('candidates', [])),
                'b_relation': ca.get('B', {}).get('relation', ''),
                'b_disclosed': ca.get('B', {}).get('disclosed', ''),
                'b_gap': ca.get('B', {}).get('gap', ''),
                'c_relation': ca.get('C', {}).get('relation', ''),
                'c_disclosed': ca.get('C', {}).get('disclosed', ''),
                'c_gap': ca.get('C', {}).get('gap', ''),
                'd_relation': ca.get('D', {}).get('relation', ''),
                'd_disclosed': ca.get('D', {}).get('disclosed', ''),
                'd_gap': ca.get('D', {}).get('gap', ''),
                'f_relation': ca.get('F', {}).get('relation', ''),
                'f_disclosed': ca.get('F', {}).get('disclosed', ''),
                'f_gap': ca.get('F', {}).get('gap', ''),
                'crowded': e.get('crowded', ''),
                'gap_hook': e.get('gap_hook', ''),
                'deep_review': e.get('deep_review', ''),
                'notable': e.get('notable', ''),
            }
            writer.writerow(row)

    return len(entries)


def main():
    print('Loading ledger...')
    expected_ids, ledger_pubno = load_ledger()
    print(f'  Expected usable lit_ids: {len(expected_ids)}')

    if len(expected_ids) != EXPECTED_COUNT:
        print(
            f'FATAL: ledger has {len(expected_ids)} usable IDs, '
            f'expected {EXPECTED_COUNT}',
            file=sys.stderr,
        )
        sys.exit(1)

    print('Loading scan batches...')
    entries = load_all_batches(ledger_pubno)
    actual_ids = set(entries.keys())

    print(f'  Actual scanned IDs: {len(actual_ids)}')

    # Assertions
    unexpected = actual_ids - expected_ids
    missing = expected_ids - actual_ids

    if unexpected:
        print(
            f'FATAL: unexpected IDs in scan: {sorted(unexpected)}',
            file=sys.stderr,
        )
        sys.exit(1)

    if missing:
        print(
            f'FATAL: missing IDs from scan: {sorted(missing)}',
            file=sys.stderr,
        )
        sys.exit(1)

    if len(actual_ids) != EXPECTED_COUNT:
        print(
            f'FATAL: expected {EXPECTED_COUNT} entries, got {len(actual_ids)}',
            file=sys.stderr,
        )
        sys.exit(1)

    # All assertions passed
    print(f'  All {EXPECTED_COUNT} IDs verified: actual == expected')

    print(f'Writing matrix to {OUTPUT_PATH}...')
    rows = build_matrix(entries)
    print(f'  Wrote {rows} rows')
    print('DONE')


if __name__ == '__main__':
    main()
