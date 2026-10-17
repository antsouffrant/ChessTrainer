#!/usr/bin/env python3
"""Convert a complete Coach export to a de-identified, reproducible benchmark.

Keep only observable chess positions, ratings, model versions and reviewer
proposals. Do not redistribute account identifiers, game links or usernames.
Proposals are not verified ground truth. Chat entries are deliberately excluded.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

ALLOW = (
    'feedback_type', 'rating', 'review_status', 'learning_mode',
    'position_category', 'motif_at_vote_key', 'primary_motif_key',
    'current_primary_motif_key', 'current_primary_motif_confidence',
    'classifier_version_at_vote', 'current_classifier_version',
    'coaching_version', 'current_coaching_version',
    'fen', 'previous_fen', 'opponent_move_uci',
    'played_move_uci', 'played_move_san', 'best_move_uci', 'best_move_san',
    'eval_before_cp', 'eval_after_cp', 'centipawn_loss', 'mate_before',
    'best_pv_uci', 'played_pv_uci', 'alternative_pvs_json',
    'critical_events_json', 'explanatory_lines_json', 'content_snapshot',
    'current_explanation', 'suggested_text', 'suggested_motif_key',
)


def transform(rows):
    for raw in rows:
        if raw.get('feedback_type') not in {'position', 'explanation', 'motif'}:
            continue
        item = {key: raw.get(key, '') for key in ALLOW}
        # All ratings for a position share a group so cross-field coherence
        # can be analyzed without preserving game URLs or account identifiers.
        position = '|'.join((raw.get('fen', ''), raw.get('best_move_uci', ''),
                             raw.get('played_move_uci', '')))
        item['position_group'] = hashlib.sha256(position.encode('utf-8')).hexdigest()[:16]
        item['case_id'] = hashlib.sha256((position + '|' + raw['feedback_type']).encode('utf-8')).hexdigest()[:20]
        yield item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    with open(args.input, encoding='utf-8-sig', newline='') as source:
        records = list(transform(csv.DictReader(source)))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as destination:
        for item in records:
            destination.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f'{len(records)} anonymized feedback rows to {args.output}')


if __name__ == '__main__':
    main()
