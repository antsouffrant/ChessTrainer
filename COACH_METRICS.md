## v83 · Message-specific approval dimensions

The Approval chart now includes **Continuation type**. It counts thumbs-up over all rated **individual messages/continuations**: solving lines (including legacy explanation votes), earlier/game moves, and other chat coaching. This chart is different from the older **Feedback area** grouping, which intentionally retains distinct-rated-position denominators for historical comparison. The recent feedback table and CSV include `continuation_key` (`solving` for historical solving ratings and the UCI root for failed/game moves), and an optional continuation filter. Correction/regression rows retain the same continuation key. As of v86, all ratings are recorded in an immutable event log keyed by stable position and continuation dictionaries. Charts count only the latest effective rating per item and coaching version, while the Coach CSV retains repeated feedback events for longitudinal review.

---

# Coach analytics — two focused percentage charts (v75)

Coach maintains **two distinct measurements**. Neither is the complement of
nor should be combined arithmetically with the other.

## Headline cards

- **Training position / explanation approval rates**: retained thumbs-up ratings
  ÷ retained thumbs ratings *in that area* (rating-level).
- **Context / move type / primary learning motif change rates**: number of
  distinct solved positions with an active user-selected replacement that
  differs from the *current* coach prediction ÷ total solved positions in
  scope (position-level). Untouched, cleared, and changed-back selections count
  as unchanged.
- The separate **Chat coaching approval** headline card is **hidden** for now.
  Chat votes still exist, appear in the default Approval chart, and remain
  available in full feedback exports.

## Two charts, two independent category selectors

Chart controls live **inside their respective chart panels**, not in the main
filter form. Each chart selects only a grouping/category; the metric is fixed.

### Changes · Change rate

Default group: **Primary learning motif** (the lesson-assigned motif). Each row
reports distinct solved positions with **any** corrected taxonomy field ÷ all
solved positions in that motif. The same changed position counts **once**, even
if its context, move type, and motif were all corrected.

Other groups: opening, context, move type, learning mode, lesson, game list,
coach version, and **Changed field** (three separate rows for context, move type,
learning motif). These are category choices, not additional metric settings.

### Approvals · Approval rate

Default group: **Feedback area**: Training positions, Explanations, Chat coaching.
Each area has its own thumbs-up/total-rated-positions rate. One position with
multiple thumbs-up chat messages counts **once** for that area. Unrated positions
are **not** treated as downvotes.

Other groups: primary motif, opening, context, move type, learning mode, lesson,
game list, and coach version. For non-feedback-area groups, the approval
numerator is the number of distinct rated solved positions with **any** positive
thumb across the three areas; the denominator is distinct solved positions with
**any** thumbs vote. A position appears only once within each group. Each bar
uses a 0–100% axis and includes explicit numerator/denominator counts.

Chart category selectors apply to the charts only. Global game-list, position,
opening, context, type, lesson, mode, and version filters still define the
population. Global record-type and thumbs-rating filters affect the recent
feedback and CSV, not the chart numerator/denominator. The two charts operate
on the same underlying saved ratings and taxonomy selections and introduce
**no new data or schema**.

### Historical version caveat

Approval by coach version uses the version snapshotted with feedback.
Taxonomy changes compare editable selections against the **current** model
labels; historical taxonomy change rates cannot be reconstructed. If an older
version has thumbs ratings but no solved positions currently assigned that
version, its change denominator is absent (shown as a dash). Older chat ratings
without saved versions use the existing current-version fallback.

## Validation

```bash
python -m unittest discover -s tests -p 'test_coach_metric_charts_v75.py'
python -m unittest discover -s tests -p 'test_coach_comparison_v74.py'
node --test tests/*.cjs
```

Existing Coach, regression, position, lesson, and Player data are preserved.
No Stockfish run or metadata refresh is required to populate these charts.
