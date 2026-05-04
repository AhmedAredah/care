"""Crash-report-specific PII recognizers."""
from __future__ import annotations

from care.pii.recognizers import (
    address,
    case_number,
    date_of_birth,
    driver_license,
    email,
    insurance_policy,
    license_plate,
    medical_info,
    person_name,
    phone,
    report_number,
    signature,
    vin,
)


def test_vin_matches_17_chars_no_iqo() -> None:
    # 1HGCM82633A004352 is a real-format VIN with a valid mod-11 check
    # digit (position 9 = 3 matches the expected 3).
    matches = vin.find("VIN: 1HGCM82633A004352 sample")
    assert len(matches) == 1
    assert matches[0].text == "1HGCM82633A004352"


def test_vin_rejects_strings_with_i_o_q() -> None:
    # Contains "I" — not a valid VIN char.
    matches = vin.find("INVALID: I1234567890123456")
    assert matches == []


def test_vin_accepts_nhtsa_documentation_examples() -> None:
    """A spread of well-formed VINs whose check digit is valid.

    Verification: each VIN was hand-computed against the 49 CFR §565
    transliteration table + weights vector ``[8,7,6,5,4,3,2,10,0,9,
    8,7,6,5,4,3,2]`` to confirm position 9 matches.
    """
    cases = [
        "1M8GDM9AXKP042788",  # NHTSA vPIC documentation example (check = X)
        "1HGCM82633A004352",  # Honda Accord 2003 (check = 3)
    ]
    for v in cases:
        matches = vin.find(f"VIN {v} reported.")
        assert len(matches) == 1, f"expected match for {v}"
        assert matches[0].text == v


def test_vin_rejects_check_digit_failures() -> None:
    """A 17-char string in the VIN alphabet whose mod-11 check digit
    is wrong must be rejected — it's a false-positive (random ID,
    transaction number, OCR error), not a real VIN."""
    # Same as the NHTSA example with position 9 mutated X -> Z.
    text = "VIN 1M8GDM9AZKP042788 in narrative."
    matches = vin.find(text)
    assert matches == [], f"unexpected match: {matches}"


def test_vin_rejects_random_alphanumeric_seventeen_char_strings() -> None:
    """Random 17-char strings happen to fit the alphabet but aren't
    VINs — the check digit catches the great majority of them."""
    matches = vin.find("Reference ABCDEFGHJKLMNPRST attached.")
    # ABCDEFGHJKLMNPRST is alphabetic only, fits the alphabet, but
    # almost certainly fails the check digit. Confirm.
    assert matches == []


def test_phone_matches_dash_format() -> None:
    matches = phone.find("call 555-123-4567 today")
    assert len(matches) == 1
    assert matches[0].text == "555-123-4567"


def test_phone_matches_paren_format() -> None:
    matches = phone.find("call (555) 123-4567")
    assert len(matches) == 1


def test_email_basic() -> None:
    matches = email.find("contact jdoe@example.com")
    assert len(matches) == 1
    assert matches[0].text == "jdoe@example.com"


def test_address_matches_street_format() -> None:
    matches = address.find("at 123 Main Street and the corner")
    assert len(matches) == 1
    assert "123 Main Street" in matches[0].text


def test_dob_label_required() -> None:
    matches = date_of_birth.find("DOB: 01/02/1990 incident date 03/04/2024")
    assert len(matches) == 1
    assert matches[0].text == "01/02/1990"


def test_dob_rejects_impossible_calendar_dates() -> None:
    """Feb 30, month 13, day 99 — the regex matches but the date
    constructor refuses, so the recognizer drops them."""
    matches = date_of_birth.find(
        "DOB 02/30/1985 DOB 13/45/1990 DOB 99/99/2000"
    )
    assert matches == []


def test_dob_rejects_future_year() -> None:
    """Year > current year is implausible for a birthdate."""
    matches = date_of_birth.find("DOB 01/02/3024 reported.")
    assert matches == []


def test_dob_rejects_year_before_1900() -> None:
    """Year < 1900 is rejected as implausible for a person on a
    crash report — also catches the most common 2-digit-year format
    when stringified incorrectly (e.g., year 85)."""
    matches = date_of_birth.find("DOB 01/02/1875 reported.")
    assert matches == []


def test_dob_rejects_two_digit_year() -> None:
    """The recognizer requires a four-digit year — two-digit years
    are ambiguous (1985 vs 2085) and rejected to avoid the
    century-pivot drift problem across releases."""
    matches = date_of_birth.find("DOB 01/02/85 reported.")
    assert matches == []


def test_dob_accepts_leap_day() -> None:
    """Feb 29 on a leap year is a legitimate birthdate."""
    matches = date_of_birth.find("DOB: 02/29/1992 reported.")
    assert len(matches) == 1
    assert matches[0].text == "02/29/1992"


def test_dob_rejects_leap_day_on_non_leap_year() -> None:
    matches = date_of_birth.find("DOB: 02/29/1991 reported.")
    assert matches == []


def test_driver_license_label_required() -> None:
    matches = driver_license.find("Driver's License: ABC1234567")
    assert len(matches) == 1
    assert matches[0].text == "ABC1234567"


def test_driver_license_no_match_without_label() -> None:
    assert driver_license.find("ABC1234567 standalone") == []


def test_license_plate_label_required() -> None:
    matches = license_plate.find("Plate: ABC1234")
    assert len(matches) == 1
    assert matches[0].text == "ABC1234"


def test_insurance_policy_label_required() -> None:
    matches = insurance_policy.find("Policy: P-1234567")
    assert len(matches) == 1
    assert matches[0].text == "P-1234567"


def test_report_number_label_required_uppercase_value() -> None:
    matches = report_number.find("Report number: EX-CR-12345")
    assert len(matches) == 1
    assert matches[0].text == "EX-CR-12345"


def test_report_number_does_not_falsely_match_form_word() -> None:
    """Critical fix: ``Report Form`` must NOT capture "Form" as a number."""
    assert report_number.find("Example Crash Report Form: EX-CR-12345") == []


def test_case_number_label_required() -> None:
    matches = case_number.find("Case #: ABC-12345")
    assert len(matches) == 1
    assert matches[0].text == "ABC-12345"


def test_person_name_contextual() -> None:
    matches = person_name.find("Officer Smith arrived first")
    assert any(m.text == "Smith" for m in matches)


def test_person_name_after_named_anchor() -> None:
    """``named`` is a role anchor too — "the witness named X" is a
    common crash-report phrasing where the name follows the verb
    rather than a noun role. The recognizer must fire on this shape."""
    matches = person_name.find("Witness named JANE DOE testified")
    assert any(m.text.upper().startswith("JANE") for m in matches)


def test_person_name_role_anchor_is_case_insensitive() -> None:
    """Form fields and OCR output often emit the role anchor in
    upper-case ("DRIVER John Smith"). The recognizer's role list is
    case-insensitive so both prose and form-field shapes match."""
    matches = person_name.find("DRIVER John Smith was at the wheel")
    assert any(m.text == "John Smith" for m in matches)


def test_person_name_does_not_match_bare_placeholder() -> None:
    """Without any role anchor, "JOHN DOE" must NOT match the
    recognizer. Regex isn't a general name detector — operators who
    need that should add an NER provider to the chain."""
    matches = person_name.find("JOHN DOE walked in")
    assert matches == []


def test_person_name_skips_single_letter() -> None:
    # "Driver A" (single capital letter) must not match — too short.
    matches = person_name.find("Driver A made an unsafe lane change")
    assert all(m.text != "A" for m in matches)


def test_signature_label_required() -> None:
    matches = signature.find("Signature: J. Smith")
    assert len(matches) == 1
    assert "J. Smith" in matches[0].text


def test_medical_info_keywords() -> None:
    matches = medical_info.find("Driver was transported to hospital due to injury.")
    types = [m.text.lower() for m in matches]
    assert "hospital" in types
    assert "injury" in types
