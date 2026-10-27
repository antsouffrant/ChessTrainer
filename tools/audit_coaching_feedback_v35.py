"""Audit *all* distinct rated continuations in a feedback CSV.

No manual case selection; newest event per position+continuation is used.
This estimates concision, motif grounding and unsupported-claim frequency;
these structural proxies are NOT predicted user approval ratings. No input
rows or usernames are written to disk by the audit.

Usage: python tools/audit_coaching_feedback_v35.py path/to/feedback.csv
"""
from __future__ import annotations
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from coaching.narrative_composition.decision_pipeline import coach_decision


def audit(path):
    with open(path,encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    ratings=[r for r in rows if r.get('feedback_type')=='explanation']
    latest={}
    for r in sorted(ratings,key=lambda row:int(row.get('feedback_event_id') or 0)):
        latest[(r.get('position_key'),r.get('continuation_key'))]=r
    results=[]
    for r in latest.values():
        key=r.get('continuation_key') or ''
        solve=key=='solving'
        uci=r.get('best_move_uci') if solve else key.removeprefix('game:')
        if not uci or len(uci) not in (4,5):continue
        try:
            data=json.loads(r.get('explanatory_lines_json') or '{}')
        except (TypeError,ValueError):data={}
        lines=data.get('lines') or []
        branch=next((l for l in lines if isinstance(l,dict) and l.get('root_uci')==uci),{})
        plies=branch.get('plies') or []
        san=plies[0].get('san') if plies else None
        if solve:san=r.get('best_move_san') or san
        try:
            out=coach_decision(r,{'move_uci':uci,'move_san':san or uci,'correct':int(solve)},
                   correct=solve,motif_key=r.get('primary_motif_key'))
        except Exception:
            continue
        results.append((r,out))
    word=lambda text:len(str(text or '').split())
    return {
        'feedback_events':len(rows),
        'distinct_feedback_positions':len({r.get('position_key') for r in rows}),
        'explanation_vote_events':len(ratings),
        'latest_explanation_decisions':len(latest),
        'latest_explanation_negative':sum(r.get('rating')=='-1' for r in latest.values()),
        'latest_explanation_positive':sum(r.get('rating')=='1' for r in latest.values()),
        'previewed_decisions':len(results),
        'v34_mean_words':round(statistics.mean(word(r.get('content_snapshot')) for r,_ in results),1) if results else None,
        'v35_mean_words':round(statistics.mean(word(o['text']) for _,o in results),1) if results else None,
        'v35_max_words':max((word(o['text']) for _,o in results),default=0),
        'v35_grounded_motif_events':sum(o['motif_alignment']=='motif_grounded' for _,o in results),
        'v35_no_specific_refutation_or_mechanism':sum(o['finding_kind']=='insufficient' for _,o in results),
        'v35_validation_fallbacks':sum(bool(o['validation_problems']) for _,o in results),
        'v35_pv_transcription_phrases':sum('Your opponent can respond' in o['text'] or
                                         'You can then play' in o['text'] for _,o in results),
        'preview_limitations':'Offline saved-variation replay; independent board legality and actual learner approval require full local chess environment and new blinded evaluation.'
    }

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: audit_coaching_feedback_v35.py feedback.csv')
    print(json.dumps(audit(sys.argv[1]),indent=2))
