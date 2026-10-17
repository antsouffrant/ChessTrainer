#!/usr/bin/env python3
"""Summarize the complete rated Coach history without running a chess engine.

This measures *voluntary feedback*, not out-of-sample chess accuracy. To
measure net changes, run evaluate_coach_feedback.py on the exact same fixture
before and after a model revision and review the changed outputs. User text
proposals are not chess-verified ground truth.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import json


def summarize(records):
    rows = [r for r in records if r.get('feedback_type') in {'position', 'motif', 'explanation'}]
    counts = Counter((r['feedback_type'], str(r['rating'])) for r in rows)
    by_position = defaultdict(dict)
    for row in rows:
        by_position[row['position_group']][row['feedback_type']] = int(row['rating'])
    pairs = Counter((v['motif'], v['explanation']) for v in by_position.values()
                    if 'motif' in v and 'explanation' in v)
    replacements = Counter((r.get('motif_at_vote_key') or r.get('primary_motif_key'),
                            r.get('suggested_motif_key')) for r in rows
                           if r['feedback_type'] == 'motif' and str(r['rating']) == '-1'
                           and r.get('suggested_motif_key'))
    approvals = defaultdict(lambda: Counter())
    for row in rows:
        if row['feedback_type'] == 'motif':
            key = row.get('motif_at_vote_key') or row.get('primary_motif_key')
            approvals[key][str(row['rating'])] += 1
    return counts, pairs, replacements, approvals


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', default='tests/fixtures/coach_feedback_full_v64.jsonl')
    opts = ap.parse_args()
    with Path(opts.input).open(encoding='utf-8') as f:
        rows = [json.loads(l) for l in f if l.strip()]
    counts, pairs, replacements, approvals = summarize(rows)
    print(f'Ratings: {len(rows)}; positions: {len({r["position_group"] for r in rows})}')
    for area in ('position', 'motif', 'explanation'):
        yes, no = counts[area, '1'], counts[area, '-1']
        print(f'{area}: +{yes} / -{no} ({yes/(yes+no):.1%} approval among rated)')
    print('Joint motif/explanation ratings:', dict(sorted(pairs.items())))
    print('Most frequent proposed motif substitutions:')
    for (before, after), count in replacements.most_common(12):
        print(f'  {before} -> {after}: {count}')
    print('Motif approval among rated (n >= 3):')
    for name, tally in sorted(approvals.items(), key=lambda row: -(sum(row[1].values()))):
        n = sum(tally.values())
        if n >= 3:
            print(f'  {name}: {tally["1"]}/{n}')


if __name__ == '__main__':
    main()
