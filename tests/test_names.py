from chatting.names import People, normalize, slug


def test_normalize_ignores_accents_case_and_punctuation():
    assert normalize("Călin_B.") == normalize("calin b") == "calinb"
    assert normalize("Șerban") == "serban"


def test_non_latin_and_symbol_names_stay_distinct():
    assert normalize("Миша") != normalize("Саша")
    assert normalize("🦊") and normalize("🦊") != normalize("🐸")
    assert normalize("Миша") == normalize("миша")
    people = People()
    assert people.same("🦊", "🦊") and not people.same("🦊", "🐸")
    assert not people.same("", "")


def test_slug():
    assert slug("Călin M.") == "calin-m"
    assert slug("Миша") == "миша"
    assert slug("🦊") != slug("🐸") and slug("🦊").startswith("person-")
    assert slug("") == "unnamed"


def test_people_aliases():
    people = People({"Călin": ["calin_b", "CB"]})
    assert people.canonical("  CB ") == "Călin"
    assert people.same("Calin_B", "călin")
    assert people.canonical("Someone Else") == "Someone Else"
