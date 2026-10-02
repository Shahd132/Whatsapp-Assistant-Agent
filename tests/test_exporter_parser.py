from app.export_parser import build_pairs, parse_messages

BRACKET = """[5:33 pm, 29/09/2026] Mona: انت فين
[5:33 pm, 29/09/2026] Sam: انا في الكلية
[5:34 pm, 29/09/2026] Mona: هتخلصي امتى
[5:34 pm, 29/09/2026] Sam: هخلص حوالي 6
[5:35 pm, 29/09/2026] Mona: ماشي
[5:35 pm, 29/09/2026] Sam: اشطا
"""

ANDROID = """29/09/2026, 5:33 pm - Messages and calls are end-to-end encrypted.
29/09/2026, 5:33 pm - Mona: ازيك
29/09/2026, 5:34 pm - Sam: كله تمام
وانت؟
29/09/2026, 5:35 pm - Mona: <Media omitted>
29/09/2026, 5:36 pm - Mona: تمام
29/09/2026, 5:36 pm - Sam: ماشي
"""


def test_bracket_format_pairs_and_digit_filter():
    pairs = build_pairs(parse_messages(BRACKET), owner="Sam")
    assert {"incoming": "انت فين", "reply": "انا في الكلية"} in pairs
    assert {"incoming": "ماشي", "reply": "اشطا"} in pairs
    assert all("6" not in p["reply"] for p in pairs)  # replies with digits are dropped
    assert len(pairs) == 2


def test_android_format_multiline_and_media_skipped():
    messages = parse_messages(ANDROID)
    assert ("Sam", "كله تمام وانت؟") in messages  # the second line was joined
    pairs = build_pairs(messages, owner="Sam")
    assert {"incoming": "ازيك", "reply": "كله تمام وانت؟"} in pairs
    assert {"incoming": "تمام", "reply": "ماشي"} in pairs  # media message ignored
    assert all("omitted" not in p["incoming"].lower() for p in pairs)


def test_unknown_owner_name_gives_no_pairs():
    assert build_pairs(parse_messages(BRACKET), owner="Nobody") == []


def test_mid_chat_system_lines_are_not_glued_onto_messages():
    text = (
        "29/09/2026, 5:33 pm - Mona: ازيك\n"
        "29/09/2026, 5:34 pm - Sam: كله تمام\n"
        "29/09/2026, 5:35 pm - Missed voice call\n"
        "29/09/2026, 5:36 pm - Mona: ماشي\n"
        "29/09/2026, 5:36 pm - Sam: اشطا\n"
    )
    messages = parse_messages(text)
    assert ("Sam", "كله تمام") in messages  # nothing appended from the "Missed voice call" line
    assert len(messages) == 4