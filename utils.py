#!/usr/bin/env python3
"""
Utility functions used by the GitHub Actions workflow.
Handles AIRAC cycles, date synchronization, and region loading.
"""

import json
import argparse
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------
FIRST_AIRAC_DATE = datetime(2025, 1, 23, tzinfo=timezone.utc)
AIRAC_CYCLE_DAYS = 28


# ---------------------------------------------------------------------
#  AIRAC Utilities
# ---------------------------------------------------------------------
def get_current_airac(debug=False):
    """Return the current AIRAC cycle as (cycle_string, next_start_date)."""
    now = datetime.now(timezone.utc)
    delta_days = (now - FIRST_AIRAC_DATE).days

    if debug:
        print(f"[DEBUG] Now: {now.isoformat()}")
        print(f"[DEBUG] Reference AIRAC start: {FIRST_AIRAC_DATE.date()}")
        print(f"[DEBUG] Days since reference: {delta_days}")

    if delta_days < 0:
        if debug:
            print("[DEBUG] Before first AIRAC reference date.")
        return f"{FIRST_AIRAC_DATE.year % 100:02d}01", FIRST_AIRAC_DATE

    # Compute current cycle number and year reset
    cycle_number = (delta_days // AIRAC_CYCLE_DAYS) + 1
    year_short = now.year % 100
    cycles_this_year = (now - datetime(now.year, 1, 1, tzinfo=timezone.utc)).days // AIRAC_CYCLE_DAYS + 1

    if cycles_this_year > 13:
        cycles_this_year = 1

    if debug:
        print(f"[DEBUG] Current AIRAC cycle number this year: {cycles_this_year}")
        print(f"[DEBUG] Next AIRAC start: {(now + timedelta(days=AIRAC_CYCLE_DAYS)).date()}")

    return f"{year_short:02d}{cycles_this_year:02d}", now + timedelta(days=AIRAC_CYCLE_DAYS)


def list_future_airacs(months=12, debug=False):
    """Return a list of AIRAC cycles for the next N months."""
    result = []
    current, start = get_current_airac()
    date = start
    while len(result) < months * 12 // AIRAC_CYCLE_DAYS:
        delta_days = (date - FIRST_AIRAC_DATE).days
        cycle_number = (delta_days // AIRAC_CYCLE_DAYS) + 1
        year_short = date.year % 100
        cycles_this_year = (date - datetime(date.year, 1, 1, tzinfo=timezone.utc)).days // AIRAC_CYCLE_DAYS + 1
        result.append((f"{year_short:02d}{cycles_this_year:02d}", date.strftime("%Y-%m-%d")))
        date += timedelta(days=AIRAC_CYCLE_DAYS)
    if debug:
        print("[DEBUG] Upcoming AIRAC cycles:")
        for code, date in result:
            print(f"  - {code} → {date}")
    return result


def is_airac_start(today=None, debug=False):
    """Return True if today matches a 28-day AIRAC boundary."""
    if today is None:
        today = datetime.now(timezone.utc).date()
    delta_days = (today - FIRST_AIRAC_DATE.date()).days
    match = delta_days >= 0 and delta_days % AIRAC_CYCLE_DAYS == 0
    if debug:
        print(f"[DEBUG] Today: {today}")
        print(f"[DEBUG] Days since first AIRAC: {delta_days}")
        print(f"[DEBUG] Is AIRAC boundary: {match}")
    return match


# ---------------------------------------------------------------------
#  Region Utilities
# ---------------------------------------------------------------------
def load_regions(path="pipeline-config.json", debug=False):
    """Return a list of regions as prefix:bbox:zoom."""
    with open(path) as f:
        data = json.load(f)

    regions_list = []
    for item in data:
        prefix = item["oaci_prefix"]
        bbox_str = ",".join(str(x) for x in item["bbox"])
        zoom_str = ",".join(str(x) for x in item["zoom"])
        entry = f"{prefix}:{bbox_str}:{zoom_str}"
        regions_list.append(entry)

        if debug:
            print(f"[DEBUG] Loaded region: {entry}")

    return regions_list


def list_region_names(path="pipeline-config.json", debug=False):
    """Return a comma-separated string of unique OACI prefixes."""
    with open(path) as f:
        data = json.load(f)
    prefixes = sorted(set(item["oaci_prefix"] for item in data))
    if debug:
        print(f"[DEBUG] Region prefixes found: {prefixes}")
    return ", ".join(prefixes)


# ---------------------------------------------------------------------
#  CLI for testing/debugging
# ---------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIRAC/Region utilities")
    parser.add_argument("command", choices=["airac", "airac_current_only", "regions", "region_names", "is_start", "future"], help="Command to run")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    if args.command.startswith("airac"):
        code, next_start = get_current_airac(debug=args.debug)
        if args.command == "airac":
            print(f"Current AIRAC: {code}")
            print(f"Next cycle starts on: {next_start.date()}")
        elif args.command == "airac_current_only":
            print(f"{code}")

    elif args.command == "regions":
        for region in load_regions(debug=args.debug):
            print(region)

    elif args.command == "region_names":
        print(list_region_names(debug=args.debug))

    elif args.command == "is_start":
        print("1" if is_airac_start(debug=args.debug) else "0")

    elif args.command == "future":
        list_future_airacs(debug=args.debug)
