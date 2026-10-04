from app.export_parser import build_pairs, parse_messages

IOS = """[5:33 pm, 29/09/2026] Sara: are you coming
[5:34 pm, 29/09/2026] Me: ايوه جاية
[5:35 pm, 29/09/2026] Sara: ok
[5:36 pm, 29/09/2026] Me: تمام"""

ANDROID = "29/09/2026, 5:33 pm - Sara: hi\n29/09/2026, 5:34 pm - Me: اهلا"


def test_parses_ios_and_android_formats():
    assert parse_messages(IOS)[0] == ("Sara", "are you coming")
    assert parse_messages(ANDROID) == [("Sara", "hi"), ("Me", "اهلا")]


def test_multiline_message_is_joined_but_system_lines_are_not():
    text = "[5:33 pm, 29/09/2026] Sara: first line\nsecond line\n[5:34 pm, 29/09/2026] Missed voice call"
    assert parse_messages(text) == [("Sara", "first line second line")]


def test_pairs_group_consecutive_messages():
    pairs = build_pairs(parse_messages(IOS), owner="Me")
    assert pairs == [{"incoming": "are you coming", "reply": "ايوه جاية"}, {"incoming": "ok", "reply": "تمام"}]


def test_replies_with_digits_or_too_long_are_dropped():
    msgs = [("A", "when"), ("Me", "at 5"), ("A", "where"), ("Me", "x" * 200), ("A", "ok"), ("Me", "تمام")]
    assert build_pairs(msgs, "Me") == [{"incoming": "ok", "reply": "تمام"}]


def test_media_links_and_duplicates_are_skipped():
    msgs = [("A", "image omitted"), ("Me", "nice"), ("A", "hi"), ("Me", "اهلا"), ("A", "hi"), ("Me", "اهلا")]
    assert build_pairs(msgs, "Me") == [{"incoming": "hi", "reply": "اهلا"}]
