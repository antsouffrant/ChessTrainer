#!/usr/bin/env python3

from datetime import datetime, timezone
import os

import requests


USERNAME = "antsouffrant"
YEAR = 2026
PERF_TYPE = "blitz"

OUTPUT_DIR = os.path.join(os.getcwd(), "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"{USERNAME}_{YEAR}_{PERF_TYPE}.pgn")


def to_unix_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    since = to_unix_ms(datetime(YEAR, 1, 1, tzinfo=timezone.utc))
    until = to_unix_ms(datetime(YEAR + 1, 1, 1, tzinfo=timezone.utc)) - 1

    url = f"https://lichess.org/api/games/user/{USERNAME}"

    params = {
        "since": since,
        "until": until,
        "perfType": PERF_TYPE,
        "clocks": "true",
        "opening": "true",
        "evals": "false",
    }

    headers = {
        "Accept": "application/x-chess-pgn",
        "User-Agent": "antsouffrant-chess-trainer/0.1",
    }

    print(f"Downloading {YEAR} {PERF_TYPE} games for {USERNAME}...")

    with requests.get(
        url,
        params=params,
        headers=headers,
        stream=True,
        timeout=(15, 300),
    ) as response:
        response.raise_for_status()

        with open(OUTPUT_FILE, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    print(f"Saved PGN archive to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
