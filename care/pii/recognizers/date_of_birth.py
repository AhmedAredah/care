"""Date-of-birth recognizer (label-anchored — incident dates are intentionally NOT matched).

The regex captures any digit-shaped date after a ``DOB``/``D.O.B.``/
``date of birth``/``born`` label, but the regex alone cannot tell
``02/30/1985`` (Feb 30 doesn't exist) from ``02/28/1985``. We parse
each match through ``datetime.date`` to enforce a real calendar date
and reject ones that are clearly not birthdays — year out of
``[1900, current_year]`` or invalid month/day. Two-digit years are
intentionally rejected to avoid the century-pivot ambiguity (a four-
digit year is unambiguous and is the dominant form on US forms).
"""
from __future__ import annotations

import datetime as _dt
import re

from ._base import RegexRecognizer

_MIN_YEAR = 1900


class DateOfBirthRecognizer(RegexRecognizer):
    entity_type = "DATE_OF_BIRTH"
    detection_reason = "regex_dob_contextual"
    default_confidence = 0.85
    capture_group = 1
    pattern = re.compile(
        r"(?:DOB|D\.O\.B\.|date\s+of\s+birth|born)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    )

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Return True iff ``value`` parses as a real calendar date in
        ``[1900-01-01, today]``. Two-digit years are rejected — a real
        DOB on a US crash report is overwhelmingly written with four
        digits, and the alternative (pivot at current_year - 100) ages
        badly across releases.
        """
        parts = re.split(r"[/-]", value)
        if len(parts) != 3:
            return False
        try:
            month = int(parts[0])
            day = int(parts[1])
            year = int(parts[2])
        except ValueError:
            return False
        if len(parts[2]) < 4:
            return False
        today = _dt.date.today()
        if year < _MIN_YEAR or year > today.year:
            return False
        try:
            # ``date`` constructor enforces the real calendar (Feb 29 only
            # on leap years, no Apr 31, no month > 12, etc.).
            candidate = _dt.date(year, month, day)
        except ValueError:
            return False
        return candidate <= today


find = DateOfBirthRecognizer.find
