from app import contacts


def test_name_lookup_by_number_lid_and_local_format(contacts_file):
    assert contacts.name_for("201000000000@c.us") == "Mom"
    assert contacts.name_for("112257593794569@lid") == "Lulu"
    assert contacts.name_for("999999999999999@lid", number="201000000000") == "Mom"   # @lid resolved by the bridge
    assert contacts.name_for("999@c.us") is None


def test_local_and_international_numbers_match(contacts_file):
    contacts_file.write_text('{"Dad": "01012345678"}', encoding="utf-8")
    assert contacts.name_for("201012345678@c.us") == "Dad"


def test_missing_or_broken_file_means_no_contacts(contacts_file):
    contacts_file.write_text("not json", encoding="utf-8")
    assert contacts.names() == []
