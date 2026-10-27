"""Stage 3 — motif selection and taxonomy; authoritative solving-root lesson.

Alternative move refutations are evidence for learning messages but do not
become the primary motif of the solving position.
"""


def classify(primary_key, **context):
    """Delegate to the established canonical taxonomy (no new rule version)."""
    from .coaching_taxonomy import assign_taxonomy
    return assign_taxonomy(primary_key, **context)


def canonical_key(key):
    from .coaching_taxonomy import canonical_motif_key
    return canonical_motif_key(key)
