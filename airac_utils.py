#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, timezone


def get_current_airac(reference_date=None, now=None):
    """
    Returns the current AIRAC cycle number (YYNN format) and its start date.
    Cycle numbers reset each year.
    """
    if reference_date is None:
        # Important: setting the reference date here.
        # First AIRAC of 2025 starts Jan 23, 2025, see
        # https://www.eurocontrol.int/sites/default/files/2020-07/airac-cycle-dates-1.1.pdf
        reference_date = datetime(2025, 1, 23, tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)

    # Determine first AIRAC of the current year
    first_airac_of_year = reference_date
    while first_airac_of_year.year < now.year:
        first_airac_of_year += timedelta(days=28)

    # Compute current cycle number (yearly reset)
    delta_days = (now - first_airac_of_year).days
    current_cycle_number = delta_days // 28 + 1

    year_short = now.strftime("%y")
    airac_code = f"{year_short}{current_cycle_number:02d}"

    return airac_code, first_airac_of_year + timedelta(days=(current_cycle_number - 1) * 28)


def get_future_airacs(reference_date=None, months_ahead=12):
    """
    Returns a list of (AIRAC code, start date) for the next `months_ahead` months.
    """
    if reference_date is None:
        reference_date = datetime(2025, 1, 23, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    current_airac, current_start = get_current_airac(reference_date, now)

    future_airacs = []
    end_date = now + timedelta(days=months_ahead*30)
    next_cycle_start = current_start

    while next_cycle_start <= end_date:
        year_short = next_cycle_start.strftime("%y")
        cycle_number = ((next_cycle_start - datetime(next_cycle_start.year, 1, 1, tzinfo=timezone.utc)).days // 28) + 1
        airac_code = f"{year_short}{cycle_number:02d}"
        future_airacs.append((airac_code, next_cycle_start.date()))
        next_cycle_start += timedelta(days=28)

    return future_airacs


if __name__ == "__main__":
    current_airac, start_date = get_current_airac()
    print(f"Current AIRAC cycle: {current_airac} (starts on {start_date.date()})\n")

    print("Future AIRAC cycles for the next 12 months:")
    for code, start in get_future_airacs():
        print(f"{code} - starts on {start}")
