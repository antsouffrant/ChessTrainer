"""Stage 5: hard constraints on a user-visible, root-aligned message."""
from __future__ import annotations
import re

def validate_narrative(finding, content, *, max_words=55):
    problems=[]
    text=' '.join((content or '').split())
    if not text or finding.root_san not in text:
        problems.append('missing_root')
    if len(text.split())>max_words:
        problems.append('too_long')
    if finding.purpose not in ('explanation','learning'):
        problems.append('bad_purpose')
    if (finding.main_event and finding.main_event.ply>0
            and finding.main_event.san and finding.main_event.san not in text):
        problems.append('unsupported_reply_reference')
    if len(re.findall(r'\b(?:your opponent can respond|you can then play)\b',text,re.I)):
        problems.append('pv_transcription')
    return tuple(problems)
