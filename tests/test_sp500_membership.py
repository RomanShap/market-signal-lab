"""Point-in-time membership reconstruction, checked on a tiny synthetic change log."""

from datetime import date

import pandas as pd

from msl.universe.sp500 import build_membership, members_on, normalize_ticker, tickers_active_since


def _changes(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "date",
            "added_ticker",
            "added_security",
            "removed_ticker",
            "removed_security",
            "reason",
        ],
    )


CHANGES = _changes(
    [
        (date(2020, 1, 10), "NEW", "New Co", "OLD", "Old Co", "swap"),
        (date(2021, 6, 1), "OLD", "Old Co", None, None, "re-added"),
        (date(2022, 3, 15), None, None, "OLD", "Old Co", "removed again"),
    ]
)
CURRENT = {"NEW", "STAY"}


def test_intervals_are_reconstructed():
    m = build_membership(CURRENT, CHANGES)
    by = {(r.ticker, r.start_date, r.end_date) for r in m.itertuples(index=False)}
    assert by == {
        ("NEW", date(2020, 1, 10), None),
        ("OLD", None, date(2020, 1, 10)),  # member before the log begins
        ("OLD", date(2021, 6, 1), date(2022, 3, 15)),
        ("STAY", None, None),  # never in the log, in the current list
    }
    notes = m.loc[m["note"].notna(), "ticker"].tolist()
    assert notes == ["OLD"]  # only the pre-log interval is flagged uncertain


def test_members_on_respects_inclusive_start_exclusive_end():
    m = build_membership(CURRENT, CHANGES)
    assert members_on(m, date(2019, 12, 31)) == {"OLD", "STAY"}
    assert members_on(m, date(2020, 1, 10)) == {"NEW", "STAY"}  # swap day: NEW in, OLD out
    assert members_on(m, date(2021, 12, 1)) == {"NEW", "OLD", "STAY"}
    assert members_on(m, date(2022, 3, 15)) == {"NEW", "STAY"}
    assert members_on(m, date(2026, 1, 1)) == {"NEW", "STAY"}


def test_tickers_active_since_includes_past_members():
    m = build_membership(CURRENT, CHANGES)
    assert tickers_active_since(m, date(2005, 1, 1)) == ["NEW", "OLD", "STAY"]
    assert tickers_active_since(m, date(2023, 1, 1)) == ["NEW", "STAY"]


def test_rename_without_removal_is_flagged_not_dropped():
    changes = _changes([(date(2021, 1, 1), "GONE", "Gone Co", None, None, None)])
    m = build_membership({"STAY"}, changes)
    gone = m[m["ticker"] == "GONE"].iloc[0]
    assert gone.start_date == date(2021, 1, 1) and gone.end_date is None
    assert "rename" in gone.note


def test_normalize_ticker_strips_footnotes_and_blanks():
    assert normalize_ticker("BRK.B[1]") == "BRK.B"
    assert normalize_ticker(" aapl ") == "AAPL"
    assert normalize_ticker(float("nan")) is None
    assert normalize_ticker("") is None
