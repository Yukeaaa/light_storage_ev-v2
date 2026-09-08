import json
import csv

# Load all scan results
all_records = []
files = ['manual_41.jsonl', 'batch_ocr_1.jsonl', 'batch_ocr_2.jsonl', 'batch_ocr_3.jsonl', 'batch_ocr_4.jsonl', 'batch_ocr_5.jsonl']
source_map = {}
for f in files:
    with open(f'literature/manifests/mechanism_scan/{f}', encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec['_source'] = f
                all_records.append(rec)
            except json.JSONDecodeError as e:
                print(f"JSON parse error in {f}: {e}")
                print(f"  Line: {line[:100]}...")

# Deduplicate by lit_id (keep first occurrence, track duplicates)
by_id = {}
for r in all_records:
    lid = r['lit_id']
    if lid not in by_id:
        by_id[lid] = r
    else:
        existing = by_id[lid]
        # Prefer higher quality scan (markitdown > ocr)
        src_rank = {'manual_41.jsonl': 3, 'batch_ocr_1.jsonl': 2, 'batch_ocr_2.jsonl': 2, 'batch_ocr_3.jsonl': 2, 'batch_ocr_4.jsonl': 2, 'batch_ocr_5.jsonl': 2}
        if src_rank.get(r['_source'], 0) > src_rank.get(existing['_source'], 0):
            by_id[lid] = r

print(f"Total records: {len(all_records)}")
print(f"Unique lit_ids after dedup: {len(by_id)}")

# Generate mechanism_matrix.csv
fieldnames = [
    'lit_id', 'doc_kind', 'source', 'evidence_level',
    'tech_problem', 'control_objects', 'inputs', 'intermediate_state',
    'decision_action', 'feedback_target', 'degradation',
    'S1', 'S2', 'S3', 'S4', 'S5', 's_chain_notes',
    'candidates', 'candidate_assessments',
    'crowded', 'gap_hook', 'data_hint',
    'ocr_quality', 'deep_review', 'deep_review_reason', 'notable'
]

with open('literature/manifests/mechanism_scan/mechanism_matrix.csv', 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    
    for lid in sorted(by_id.keys()):
        r = by_id[lid]
        row = {
            'lit_id': r['lit_id'],
            'doc_kind': r.get('doc_kind', ''),
            'source': r.get('_source', ''),
            'evidence_level': 'FULLTEXT-MARKITDOWN' if 'manual_41' in r.get('_source', '') else 'FULLTEXT-OCR',
            'tech_problem': r.get('tech_problem', ''),
            'control_objects': '; '.join(r.get('control_objects', [])),
            'inputs': r.get('inputs', ''),
            'intermediate_state': r.get('intermediate_state', ''),
            'decision_action': r.get('decision_action', ''),
            'feedback_target': r.get('feedback_target', ''),
            'degradation': r.get('degradation', ''),
            'S1': r.get('s_chain', {}).get('S1', ''),
            'S2': r.get('s_chain', {}).get('S2', ''),
            'S3': r.get('s_chain', {}).get('S3', ''),
            'S4': r.get('s_chain', {}).get('S4', ''),
            'S5': r.get('s_chain', {}).get('S5', ''),
            's_chain_notes': r.get('s_chain_notes', ''),
            'candidates': '; '.join(r.get('candidates', [])),
            'candidate_assessments': json.dumps(r.get('candidate_assessments', {}), ensure_ascii=False),
            'crowded': r.get('crowded', ''),
            'gap_hook': r.get('gap_hook', ''),
            'data_hint': r.get('data_hint', ''),
            'ocr_quality': r.get('ocr_quality', ''),
            'deep_review': r.get('deep_review', ''),
            'deep_review_reason': r.get('deep_review_reason', ''),
            'notable': r.get('notable', '')
        }
        writer.writerow(row)

print("\nmechanism_matrix.csv written successfully")

# Summary statistics
s_levels = ['S1', 'S2', 'S3', 'S4', 'S5']
for s in s_levels:
    counts = {}
    for r in by_id.values():
        val = r.get('s_chain', {}).get(s, '无')
        counts[val] = counts.get(val, 0) + 1
    print(f"  {s}: {counts}")

# Papers with any non-无 S-chain hit
with_hit = sum(1 for r in by_id.values() if any(r.get('s_chain', {}).get(k, '无') != '无' for k in s_levels))
print(f"\nPapers with any S-chain hit: {with_hit}/{len(by_id)}")

# Papers with S chain hit >= 2 steps
with_multi = sum(1 for r in by_id.values() if sum(1 for k in s_levels if r.get('s_chain', {}).get(k, '无') != '无') >= 2)
print(f"Papers with 2+ S-chain hits: {with_multi}/{len(by_id)}")

# Candidate A relevance
with_A = [lid for lid, r in by_id.items() if 'A' in r.get('candidates', [])]
print(f"\nCandidate A relevant papers: {len(with_A)}")
for lid in sorted(with_A):
    r = by_id[lid]
    s_summary = {k: r.get('s_chain', {}).get(k, '无') for k in s_levels}
    print(f"  lit_id {lid}: {s_summary}")
    assess = r.get('candidate_assessments', {}).get('A', {})
    if assess:
        print(f"    relation: {assess.get('relation', '')}")
        print(f"    gap: {assess.get('gap', '')}")
