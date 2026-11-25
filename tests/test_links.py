"""Game link formats (the UI's side is ui/src/links.ts, tested with the same examples)."""

import re

from api.links import game_id_from_link, seat_fragment


def test_game_id_from_links():
    assert game_id_from_link("http://host:8000/?game=abc") == "abc"
    assert game_id_from_link(" http://host:8000/?join=abc ") == "abc"
    assert game_id_from_link("http://host:8000/") is None


def test_seat_fragment_matches_what_the_page_reads():
    fragment = seat_fragment("black", "tok.en")
    assert fragment == "#seat=black.tok.en"
    # The pattern ui/src/links.ts reads it with.
    match = re.fullmatch(r"#seat=(white|black)\.(.+)", fragment)
    assert match and match.groups() == ("black", "tok.en")
