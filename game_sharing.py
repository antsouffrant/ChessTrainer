"""Safe, backward-compatible sharing helpers for original chess games.

Never manufacture a Lichess link from an arbitrary imported game ID: PGN
imports may use local hashes or IDs from entirely different chess providers.
"""

import re
from urllib.parse import urlsplit


_LICHESS_GAME_PATH = re.compile(r'^/([A-Za-z0-9]{8})(?:/(?:white|black))?/?$')
_PGN_SITE_HEADER = re.compile(r'^\[Site\s+"([^"\r\n]+)"\]\s*$', re.MULTILINE)


def lichess_game_url(site, pgn=''):
    """Return a canonical HTTPS game URL only for verified lichess.org sites."""
    candidates = [site]
    if pgn:
        header = _PGN_SITE_HEADER.search(pgn)
        if header:
            candidates.append(header.group(1))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = urlsplit(str(candidate).strip())
            if parsed.scheme.lower() not in {'http', 'https'}:
                continue
            if parsed.username or parsed.password or parsed.port is not None:
                continue
            if (parsed.hostname or '').lower() not in {'lichess.org', 'www.lichess.org'}:
                continue
            match = _LICHESS_GAME_PATH.fullmatch(parsed.path)
        except ValueError:
            continue
        if match:
            return f'https://lichess.org/{match.group(1)}'
    return None


def normalize_pgn(pgn):
    return str(pgn).strip() + '\n' if pgn and str(pgn).strip() else ''


def game_pgn_filename(game_id):
    # Never insert untrusted PGN metadata into a Content-Disposition filename.
    slug = re.sub(r'[^a-zA-Z0-9_-]', '-', str(game_id or 'chess-game')).strip('-')[:56]
    return f'{slug or "chess-game"}.pgn'
