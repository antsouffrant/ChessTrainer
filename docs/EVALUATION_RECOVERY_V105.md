# Evaluation finalization invariant

For a job and active coaching version V, the fixed cohort C is never redrawn.
A current evaluation can be auto-created only when all |C| positions have
non-empty coach explanations stamped V and the coaching-refresh process is
complete. A new immutable snapshot captures the current per-position text and
taxonomy. Evaluation attempts and feedback stay scoped to that run.

Refresh finalization and a GET of Lessons/Openings invoke the same idempotent
`evaluation_runs.activate_current_evaluation`, but only the latter does a
recovery write if the previous refresh finished. If the current run exists,
return it without modifying the snapshot or progress. If no run exists and a
partial snapshot is present, rebuild only if no evaluation (including a
superseded run) references the snapshot. Otherwise surface an error, preserving
its history.

The featured tile is a discovery UI, not the evaluation datastore. A complete
current-model evaluation hides the tile but remains accessible from Coach.
Previous-model evaluations remain frozen and inaccessible from Trainer.
