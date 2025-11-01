"""Functions for fetching and processing sleep data from Mi Fit/Zepp API."""

import base64
import csv
import json
import requests
from tabulate import tabulate
from utils import to_madrid_iso


def get_band_data(auth_info: dict, from_date: str, to_date: str, output_file: str = "sleep_export.csv"):
    """
    Download data range [from_date, to_date] and build rows for CSV/table.

    Important about units:
    - dp/lt/wk already come in minutes.
    - stage[].start / stage[].stop also come in minutes (relative to the same day),
      so (stop - start) gives minutes for each segment.
    """
    print(f"[fetch] Retrieving mi band data from {from_date} to {to_date}")

    url = "https://api-mifit.huami.com/v1/data/band_data.json"
    headers = {"apptoken": auth_info["token_info"]["app_token"]}
    params = {
        "query_type": "summary",
        "device_type": "android_phone",
        "userid": auth_info["token_info"]["user_id"],
        "from_date": from_date,
        "to_date": to_date,
    }

    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()

    rows = []

    for daydata in resp.json().get("data", []):
        day = daydata["date_time"]

        summary_b = base64.b64decode(daydata.get("summary", ""))
        summary = json.loads(summary_b) if summary_b else {}

        if "slp" not in summary:
            continue

        slp = summary["slp"]

        deep  = slp.get("dp", 0)
        light = slp.get("lt", 0)
        wake  = slp.get("wk", 0)

        start_iso = to_madrid_iso(slp.get("st", 0))
        stop_iso  = to_madrid_iso(slp.get("ed", 0))

        # Calculate REM from segments
        # Sum separately mode 7 and mode 8 minutes, then expose the sum (REMTime)
        rem7 = 0
        rem8 = 0
        for s in slp.get("stage", []):
            mode = s.get("mode")
            dur = (s.get("stop", 0) - s.get("start", 0))
            if mode == 7:
                rem7 += dur
            elif mode == 8:
                rem8 += dur
            # other modes (4,5, etc.) not counted here because REM = 7 + 8

        rows.append({
            "date": day,
            "deepSleepTime": deep,
            "shallowSleepTime": light,
            "wakeTime": wake,
            "start": start_iso,
            "stop": stop_iso,
            "REMTime": rem7 + rem8,
            "naps": slp.get("nap", 0),
        })

    fields = [
        "date","deepSleepTime","shallowSleepTime","wakeTime","start","stop","REMTime","naps"
    ]
    with open(output_file, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(f"\n[done] Exported {len(rows)} rows to {output_file}\n")
    print(tabulate(rows, headers="keys", tablefmt="github"))

    return rows

