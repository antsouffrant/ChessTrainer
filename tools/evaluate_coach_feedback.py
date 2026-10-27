#!/usr/bin/env python3
"""Offline, reproducible Coach CSV/fixture audit (no Stockfish, no game retrieval).

Usage:
  python tools/evaluate_coach_feedback.py --input tests/fixtures/coach_feedback_v58.jsonl --output my_report.csv
  python tools/evaluate_coach_feedback.py --input "chess_coaching_feedback.csv" --output my_report.csv

Feedback corrections are PROPOSED reference answers, not an automatically
verified gold standard. For proposed motifs we calculate exact-match rate;
prose improvements must be reviewed as chess reasoning, not string matches.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_rows(path):
    path = Path(path)
    if path.suffix == '.jsonl':
        with path.open(encoding='utf-8') as handle:
            return [json.loads(line) for line in handle if line.strip()]
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def normalize(row):
    return {
        'case_id': row.get('case_id') or row.get('regression_case_id') or '',
        'feedback_type': row.get('feedback_type') or '',
        'rating': int(row.get('rating') or 0),
        'review_status': row.get('review_status') or '',
        'fen': row.get('fen') or '',
        'previous_fen': row.get('previous_fen') or '',
        'opponent_move_uci': row.get('opponent_move_uci') or '',
        'opponent_move_san': row.get('opponent_move_san') or '',
        'best_move_san': row.get('best_move_san') or '',
        'played_move_san': row.get('played_move_san') or '',
        'critical_events_json': row.get('critical_events_json') or '',
        'explanatory_lines_json': row.get('explanatory_lines_json') or '',
        'proactive_coach_json': row.get('proactive_coach_json') or '',
        'played_move_uci': row.get('played_move_uci') or '',
        'best_move_uci': row.get('best_move_uci') or '',
        'best_pv_uci': row.get('best_pv_uci') or '',
        'played_pv_uci': row.get('played_pv_uci') or '',
        'category': row.get('category') or row.get('position_category') or 'mistake',
        'centipawn_loss': row.get('centipawn_loss') or '0',
        'mate_before': row.get('mate_before') or '',
        'eval_before_cp': row.get('eval_before_cp') or '',
        'eval_after_cp': row.get('eval_after_cp') or '',
        'alternative_pvs_json': row.get('alternative_pvs_json') or '[]',
        'current_motif': row.get('current_motif') or row.get('motif_at_vote_key') or row.get('current_primary_motif_key') or row.get('primary_motif_key') or '',
        'suggested_motif': row.get('suggested_motif') or row.get('suggested_motif_key') or '',
        'original_text': row.get('original_text') or row.get('content_snapshot') or '',
        'suggested_text': row.get('suggested_text') or '',
    }


def analyze(rows):
    # `chess` is optional for loading fixtures/report schema, but required to
    # genuinely re-run classification or explanation generation.
    try:
        import chess
        from learning import classify_learning_concepts
        from coaching.narrative_composition.coaching import generate_coaching_text
        from coaching.board_context.proactive_coaching import prefer_evidenced_primary
    except ImportError as exc:
        raise RuntimeError('Install dependencies from requirements.txt before evaluating chess positions') from exc
    outcomes = []
    for raw in rows:
        rec = normalize(raw)
        if rec['feedback_type'] not in ('position', 'explanation', 'motif'):
            continue
        result = dict(rec)
        result.update({'predicted_motif': '', 'predicted_explanation': '',
                       'motif_matches_proposal': '', 'positive_motif_preserved': '',
                       'explanation_has_boilerplate': '', 'positive_explanation_changed': '',
                       'approved_explanation_review': '', 'assessment': '', 'error': ''})
        try:
            board = chess.Board(rec['fen'])
            best = chess.Move.from_uci(rec['best_move_uci'])
            played = chess.Move.from_uci(rec['played_move_uci'])
            if best not in board.legal_moves or played not in board.legal_moves:
                raise ValueError('Candidate move is not legal in saved FEN')
            def pv(value):
                if isinstance(value, list):
                    return value
                try:
                    obj = json.loads(value or '[]')
                    return obj if isinstance(obj, list) else []
                except (TypeError, ValueError):
                    return []
            labels = classify_learning_concepts(
                board, played, best, rec['category'], int(float(rec['centipawn_loss'] or 0)),
                mate_before=int(rec['mate_before']) if rec['mate_before'] else None,
                best_pv_uci=pv(rec['best_pv_uci']), played_pv_uci=pv(rec['played_pv_uci']),
                previous_fen=rec['previous_fen'] or None,
                opponent_move_uci=rec['opponent_move_uci'] or None)
            labels = prefer_evidenced_primary(board, labels, rec['proactive_coach_json'])
            result['predicted_motif'] = next((x.key for x in labels if x.is_primary), '')
            if rec['feedback_type'] == 'motif':
                if rec['rating'] < 0 and rec['suggested_motif']:
                    result['motif_matches_proposal'] = str(result['predicted_motif'] == rec['suggested_motif']).lower()
                if rec['rating'] > 0:
                    result['positive_motif_preserved'] = str(result['predicted_motif'] == rec['current_motif']).lower()
            if rec['feedback_type'] == 'explanation':
                prompt, explanation = generate_coaching_text(
                    fen=rec['fen'], previous_fen=rec['previous_fen'] or None,
                    opponent_move_uci=rec['opponent_move_uci'] or None,
                    opponent_move_san=rec['opponent_move_san'] or None,
                    played_move_uci=rec['played_move_uci'], played_move_san=rec['played_move_san'] or None,
                    best_move_uci=rec['best_move_uci'], best_move_san=rec['best_move_san'] or None,
                    played_pv_uci=pv(rec['played_pv_uci']),
                    best_pv_uci=pv(rec['best_pv_uci']),
                    labels=labels, category=rec['category'],
                    taxonomy_path=(__import__('coaching_taxonomy').assign_taxonomy(
                        next((x.key for x in labels if x.is_primary), labels[0].key),
                        category=rec['category'],
                        learning_mode=rec.get('learning_mode') or '',
                        is_in_check=board.is_check(),
                        root_best_is_check=(best in board.legal_moves and board.gives_check(best)))
                        if labels else None),
                    mate_before=int(rec['mate_before']) if rec['mate_before'] else None,
                    eval_before_cp=int(float(rec['eval_before_cp'])) if rec['eval_before_cp'] else None,
                    eval_after_cp=int(float(rec['eval_after_cp'])) if rec['eval_after_cp'] else None,
                    alternative_pvs_json=pv(rec['alternative_pvs_json']),
                    critical_events_json=rec['critical_events_json'] or None,
                    explanatory_lines_json=rec['explanatory_lines_json'] or None,
                    proactive_coach_json=rec['proactive_coach_json'] or None)
                result['predicted_explanation'] = explanation
                result['explanation_has_boilerplate'] = str(bool(re.search(
                    r'analyzed continuation|Why .+ falls short|Stockfish evaluates', explanation, re.I))).lower()
                # A changed previously-approved explanation must be reviewed,
                # not automatically treated as a net improvement.
                if rec['rating'] > 0:
                    changed = explanation.strip() != rec['original_text'].strip()
                    result['positive_explanation_changed'] = str(changed).lower()
                    result['approved_explanation_review'] = 'review_changed_approved' if changed else 'preserved_exactly'
                # User-proposed wording is intentionally not binary graded.
                result['assessment'] = 'manual_review_proposed_wording' if rec['rating'] < 0 else 'approved_reference'
            else:
                result['assessment'] = 'proposed_not_verified' if rec['rating'] < 0 else 'approved_reference'
        except (ValueError, TypeError, KeyError, AssertionError) as exc:
            result['error'] = str(exc)
        outcomes.append(result)
    return outcomes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args(argv)
    rows = load_rows(args.input)
    results = analyze(rows)
    if not results:
        raise SystemExit('No position/explanation/motif feedback records')
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    stats = Counter((r['feedback_type'], r['rating']) for r in results)
    proposed = [r for r in results if r['feedback_type'] == 'motif' and r['suggested_motif'] and r['rating'] < 0]
    correct = sum(r['motif_matches_proposal'] == 'true' for r in proposed)
    print('Feedback distribution:', dict(stats))
    print(f'Proposed motif agreement: {correct}/{len(proposed)} (not an independently validated score)')
    preserved = [r for r in results if r['feedback_type'] == 'motif' and r['rating'] > 0 and not r['error']]
    n_preserved = sum(r['positive_motif_preserved'] == 'true' for r in preserved)
    print(f'Previously approved motif labels retained: {n_preserved}/{len(preserved)} (not a chess truth score)')
    changed_explanations = [r for r in results if r['approved_explanation_review'] == 'review_changed_approved']
    print(f'Previously approved explanations changed and needing review: {len(changed_explanations)}')
    print(f'Report: {out}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
