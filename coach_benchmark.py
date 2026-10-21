"""Persistent, position-matched coaching model benchmark.

Cohort is created exactly once, at the first coaching-refresh request for a
list, and NEVER expanded or redrawn on subsequent refreshes. A new model's
completed refresh snapshots explanations/taxonomy without changing feedback.
Feedback is collected only on explicit user action and measured separately.
"""
from collections import defaultdict
import hashlib

SAMPLE_TARGET = 36


def _hash(job_id, position_id):
    return hashlib.sha256(f'coach-benchmark-v1:{job_id}:{position_id}'.encode()).hexdigest()


def ensure_cohort(conn, job_id, target=SAMPLE_TARGET):
    existing=conn.execute('SELECT sample_size FROM coach_benchmark_cohorts WHERE job_id=?', (job_id,)).fetchone()
    if existing is not None:
        return int(existing['sample_size'])
    rows=conn.execute('''SELECT id, fen, category, learning_mode, estimated_rating, learned
         FROM training_positions WHERE job_id=? ORDER BY id''',(job_id,)).fetchall()
    if not rows: return 0
    # Stratify by lesson mode, ability and learned state; round-robin strata
    # avoids a random sample consisting almost entirely of the majority class.
    groups=defaultdict(list)
    for row in rows:
        rating=row['estimated_rating']
        bucket=('unknown' if rating is None else
                'low' if rating < 1200 else 'mid' if rating < 1800 else 'high')
        groups[(row['learning_mode'] or 'unknown',bucket,int(row['learned'] or 0))].append(row)
    for entries in groups.values():
        entries.sort(key=lambda r:_hash(job_id,r['id']))
    selected=[]
    while len(selected)<min(target,len(rows)):
        progressed=False
        for stratum in sorted(groups):
            if groups[stratum] and len(selected)<target:
                selected.append(groups[stratum].pop(0));progressed=True
        if not progressed:break
    conn.execute('''INSERT INTO coach_benchmark_cohorts(job_id,source_count,sample_size)
       VALUES(?,?,?)''',(job_id,len(rows),len(selected)))
    conn.executemany('''INSERT INTO coach_benchmark_positions
      (job_id,position_id,ordinal,fen,category,learning_mode) VALUES (?,?,?,?,?,?)''',
      ((job_id,r['id'],i,r['fen'],r['category'],r['learning_mode'])
       for i,r in enumerate(selected)))
    return len(selected)


def snapshot_completed_refresh(conn,job_id,coaching_version,taxonomy_version):
    """Once per model version, after the final successful batch commit.

    A repeated run of the same version cannot overwrite the baseline. Captures
    position row snapshots and the taxonomy from this finished refresh.
    """
    cohort=conn.execute('SELECT sample_size FROM coach_benchmark_cohorts WHERE job_id=?',(job_id,)).fetchone()
    if not cohort: return 0
    existing=conn.execute('''SELECT id FROM coach_benchmark_runs
      WHERE job_id=? AND coaching_version=?''',(job_id,coaching_version)).fetchone()
    if existing: return 0
    rows=conn.execute('''SELECT bp.position_id,tp.coach_explanation,tp.coach_prompt,
             tx.motif_key,tx.context_key,tx.move_type_key
       FROM coach_benchmark_positions bp
       JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
       LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
       WHERE bp.job_id=? AND tp.coaching_version=?
       ORDER BY bp.ordinal''',(job_id,coaching_version)).fetchall()
    run=conn.execute('''INSERT INTO coach_benchmark_runs
       (job_id,coaching_version,taxonomy_version,expected_positions,captured_positions)
       VALUES (?,?,?,?,?)''',(job_id,coaching_version,taxonomy_version,cohort['sample_size'],len(rows)))
    conn.executemany('''INSERT INTO coach_benchmark_snapshots
      (run_id,position_id,explanation,coach_prompt,motif_key,context_key,move_type_key)
      VALUES (?,?,?,?,?,?,?)''',
      ((run.lastrowid,r['position_id'],r['coach_explanation'],r['coach_prompt'],
        r['motif_key'],r['context_key'],r['move_type_key']) for r in rows))
    return len(rows)


def benchmark_status(conn,job_id):
    cohort=conn.execute('SELECT * FROM coach_benchmark_cohorts WHERE job_id=?',(job_id,)).fetchone()
    if not cohort:return None
    available=conn.execute('''SELECT COUNT(*) FROM coach_benchmark_positions bp
      JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
      WHERE bp.job_id=?''',(job_id,)).fetchone()[0]
    versions=[]
    ratings_by_version={}
    snapshots_by_version={}
    for run in conn.execute('''SELECT id,coaching_version,taxonomy_version,
       expected_positions,captured_positions,completed_at FROM coach_benchmark_runs
       WHERE job_id=? ORDER BY id''',(job_id,)).fetchall():
        # Vote only when a user rated. Reduce repeated votes for the *same*
        # position + continuation + model to the latest event. Each attempt
        # may legitimately receive a different rating from the solve.
        votes=conn.execute('''WITH latest AS (
           SELECT e.source_position_id,e.feedback_type,e.continuation_id,e.rating,
             ROW_NUMBER() OVER (PARTITION BY e.source_position_id,e.feedback_type,
               COALESCE(e.continuation_id,'') ORDER BY e.id DESC) AS rn
           FROM feedback_events e
           JOIN coach_benchmark_positions bp ON bp.position_id=e.source_position_id
             AND bp.job_id=?
           WHERE e.coaching_version=? AND e.feedback_type='explanation')
           SELECT * FROM latest WHERE rn=1 AND rating!=0''',
           (job_id,run['coaching_version'])).fetchall()
        ratings={(r['source_position_id'],r['continuation_id']):r['rating'] for r in votes}
        ratings_by_version[run['coaching_version']]=ratings
        snapshot=conn.execute('''SELECT position_id,explanation,motif_key
               FROM coach_benchmark_snapshots WHERE run_id=?''',(run['id'],)).fetchall()
        snapshots_by_version[run['coaching_version']]={
            r['position_id']:(r['explanation'],r['motif_key']) for r in snapshot}
        taxonomy=conn.execute('''WITH latest AS (
             SELECT e.source_position_id,e.feedback_type,e.rating,
               ROW_NUMBER() OVER (PARTITION BY e.source_position_id,e.feedback_type
                 ORDER BY e.id DESC) AS rn
             FROM feedback_events e JOIN coach_benchmark_positions bp
               ON bp.position_id=e.source_position_id AND bp.job_id=?
             WHERE e.coaching_version=? AND e.feedback_type LIKE 'taxonomy_%')
             SELECT feedback_type,rating FROM latest WHERE rn=1 AND rating!=0''',
             (job_id,run['coaching_version'])).fetchall()
        taxonomy_corrected=sum(r['rating']==-1 for r in taxonomy)
        taxonomy_confirmed=sum(r['rating']==1 for r in taxonomy)
        positive=sum(v==1 for v in ratings.values());rated=len(ratings)
        versions.append({'coaching_version':run['coaching_version'],
            'taxonomy_version':run['taxonomy_version'],
            'expected':run['expected_positions'],
            'captured':run['captured_positions'],
            'rated_messages':rated,'rated_positions':len({key[0] for key in ratings}),
            'taxonomy_rated_fields':len(taxonomy),
            'taxonomy_confirmed_fields':taxonomy_confirmed,
            'taxonomy_corrected_fields':taxonomy_corrected,
            'positive':positive,
            'approval_pct':round(100*positive/rated,1) if rated else None,
            'completed_at':run['completed_at']})
    # True apples-to-apples is a matched position+continuation intersection,
    # not two approval rates measured over different rated subsets.
    comparisons=[]
    for before,after in zip(versions,versions[1:]):
        old,new=before['coaching_version'],after['coaching_version']
        a,b=ratings_by_version[old],ratings_by_version[new]
        shared=a.keys() & b.keys()
        sa,sb=snapshots_by_version[old],snapshots_by_version[new]
        common_positions=sa.keys() & sb.keys()
        comparisons.append({'from_version':old,'to_version':new,
            'paired_messages':len(shared),
            'before_approval_pct':round(100*sum(a[key]==1 for key in shared)/len(shared),1) if shared else None,
            'after_approval_pct':round(100*sum(b[key]==1 for key in shared)/len(shared),1) if shared else None,
            'paired_positions_with_snapshots':len(common_positions),
            'motif_changes':sum(sa[k][1]!=sb[k][1] for k in common_positions),
            'explanation_changes':sum(sa[k][0]!=sb[k][0] for k in common_positions)})
    return {'size':cohort['sample_size'],'source_count':cohort['source_count'],
            'available':available,'selection_version':cohort['selection_version'],
            'versions':versions,'comparisons':comparisons}


def benchmark_manifest(conn,job_id):
    return [dict(r) for r in conn.execute('''SELECT bp.position_id AS id,tp.learned
       FROM coach_benchmark_positions bp JOIN training_positions tp
       ON tp.id=bp.position_id AND tp.job_id=bp.job_id
       WHERE bp.job_id=? ORDER BY bp.ordinal''',(job_id,)).fetchall()]


def _latest_feedback(conn, job_id, coaching_version, kind):
    """Latest event per position/continuation/model; withdrawals remove the vote.

    A rating exists only when the learner provided it. A historical version
    never inherits votes or corrections recorded under a different version.
    """
    rows=conn.execute('''WITH latest AS (
      SELECT e.source_position_id AS position_id,
         COALESCE(e.continuation_id,'') AS continuation_id,e.rating,
         ROW_NUMBER() OVER (
           PARTITION BY e.source_position_id,COALESCE(e.continuation_id,'')
           ORDER BY e.id DESC) AS rn
      FROM feedback_events e
      JOIN coach_benchmark_positions bp ON bp.position_id=e.source_position_id
         AND bp.job_id=?
      WHERE e.coaching_version=? AND e.feedback_type=?
    ) SELECT position_id,continuation_id,rating FROM latest
      WHERE rn=1 AND rating!=0''',(job_id,coaching_version,kind)).fetchall()
    return {(r['position_id'],r['continuation_id']):r['rating'] for r in rows}


def benchmark_comparison(conn,job_id,model_a='',model_b=''):
    """Version-matched cohort comparisons for Coach UI; no pseudo-ratings.

    Comparisons of explanation/motif *outputs* are on common stored position
    snapshots. Approval is separately measured on overlapping *rated*
    (position, continuation) items, never the entire cohort by default.
    """
    runs=conn.execute('''SELECT id,coaching_version,expected_positions,
      captured_positions FROM coach_benchmark_runs WHERE job_id=? ORDER BY id''',
      (job_id,)).fetchall()
    versions=[r['coaching_version'] for r in runs]
    if not versions:
        return {'job_id':job_id,'versions':[],'model_a':None,'model_b':None,'comparisons':[],
                'cohort_size':0}
    model_a=model_a or versions[-1]
    model_b=model_b or 'all'
    if model_a not in versions:raise ValueError('Unknown baseline model')
    if model_b!='all' and model_b not in versions:raise ValueError('Unknown comparison model')
    if model_b==model_a:raise ValueError('Select a different comparison model')
    cohort=conn.execute('SELECT sample_size FROM coach_benchmark_cohorts WHERE job_id=?',(job_id,)).fetchone()
    run_by_version={r['coaching_version']:r for r in runs}
    def snapshot(model):
        return {r['position_id']:dict(r) for r in conn.execute('''SELECT position_id,
         explanation,motif_key,context_key,move_type_key FROM coach_benchmark_snapshots
         WHERE run_id=?''',(run_by_version[model]['id'],)).fetchall()}
    baseline=snapshot(model_a)
    approvals_a=_latest_feedback(conn,job_id,model_a,'explanation')
    targets=[v for v in versions if v!=model_a] if model_b=='all' else [model_b]
    comparisons=[]
    for name in targets:
        alternative=snapshot(name)
        common=set(baseline)&set(alternative)
        # Snapshot-to-snapshot change rates are not user-correction rates.
        diff={key:sum(baseline[p][key]!=alternative[p][key] for p in common)
              for key in ('explanation','motif_key','context_key','move_type_key')}
        approvals_b=_latest_feedback(conn,job_id,name,'explanation')
        rated=set(approvals_a)&set(approvals_b)
        positive_a=sum(approvals_a[key]==1 for key in rated)
        positive_b=sum(approvals_b[key]==1 for key in rated)
        def pct(n,d):return round(n*100/d,1) if d else None
        motif_a=_latest_feedback(conn,job_id,model_a,'taxonomy_motif')
        motif_b=_latest_feedback(conn,job_id,name,'taxonomy_motif')
        comparisons.append({
          'baseline':model_a,'comparison':name,'cohort_size':int(cohort['sample_size']) if cohort else 0,
          'shared_snapshots':len(common),
          'baseline_snapshots':len(baseline),'comparison_snapshots':len(alternative),
          'explanation_change_count':diff['explanation'],
          'explanation_change_pct':pct(diff['explanation'],len(common)),
          'motif_change_count':diff['motif_key'],
          'motif_change_pct':pct(diff['motif_key'],len(common)),
          'context_change_count':diff['context_key'],
          'context_change_pct':pct(diff['context_key'],len(common)),
          'move_type_change_count':diff['move_type_key'],
          'move_type_change_pct':pct(diff['move_type_key'],len(common)),
          'paired_ratings':len(rated),
          'baseline_positive':positive_a,'comparison_positive':positive_b,
          'baseline_approval_pct':pct(positive_a,len(rated)),
          'comparison_approval_pct':pct(positive_b,len(rated)),
          'motif_feedback_a':len(motif_a),'motif_feedback_b':len(motif_b),
          'motif_corrections_a':sum(v==-1 for v in motif_a.values()),
          'motif_corrections_b':sum(v==-1 for v in motif_b.values()),
          'motif_correction_pct_a':pct(sum(v==-1 for v in motif_a.values()),len(motif_a)),
          'motif_correction_pct_b':pct(sum(v==-1 for v in motif_b.values()),len(motif_b))})
    return {'job_id':job_id,'versions':versions,'model_a':model_a,'model_b':model_b,
            'cohort_size':int(cohort['sample_size']) if cohort else 0,
            'comparisons':comparisons}
