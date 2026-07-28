"""Workday-count helper wrapping the `chinese_calendar` package."""
import datetime

from chinese_calendar import is_workday


def workday_diff(start: datetime.date, end: datetime.date) -> int | None:
    """Count workdays strictly between start and end (exclusive of start,
    inclusive of end), matching how a lead time in workdays is normally read:
    'N workdays after the announcement'. Returns None if either date's year
    falls outside chinese_calendar's supported holiday-calendar range.
    """
    if start is None or end is None or end < start:
        return None
    try:
        count = 0
        d = start + datetime.timedelta(days=1)
        while d <= end:
            if is_workday(d):
                count += 1
            d += datetime.timedelta(days=1)
        return count
    except NotImplementedError:
        return None
