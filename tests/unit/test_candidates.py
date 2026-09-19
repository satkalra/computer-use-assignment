from replaykit.compiler.candidates import derive
from replaykit.recorder.snapshot import capture


def _ref_for(snapshot, role, index=0):
    matches = [e for e in snapshot.elements.values() if e.role == role]
    return matches[index]


def test_derive_prefers_role_and_name_for_a_uniquely_named_button(page, pages_url):
    page.goto(f"{pages_url}/login.html")
    element = _ref_for(capture(page), "button")

    candidates = derive(page, element.ref, element.role, element.name)

    assert candidates[0].role == "button" and candidates[0].name == "Log In"


def test_derive_falls_back_to_id_for_an_unnamed_input(page, pages_url):
    page.goto(f"{pages_url}/login.html")
    element = _ref_for(capture(page), "textbox")

    candidates = derive(page, element.ref, element.role, element.name)

    assert candidates[0].css == "#username"
    assert all(candidate.role is None for candidate in candidates)


def test_derive_anchors_on_text_without_walking_into_a_select_option_list(page, pages_url):
    page.goto(f"{pages_url}/transfer.html")
    to_account = _ref_for(capture(page), "combobox", index=1)

    candidates = derive(page, to_account.ref, to_account.role, to_account.name)

    assert any(candidate.xpath and "to account #" in candidate.xpath for candidate in candidates)
    assert not any(candidate.xpath and "12345" in candidate.xpath for candidate in candidates)


def test_derive_disambiguates_duplicate_button_names_by_text_anchor(page, pages_url):
    page.goto(f"{pages_url}/findtrans.html")
    find_by_amount = [element for element in capture(page).elements.values() if element.role == "button"][1]

    candidates = derive(page, find_by_amount.ref, find_by_amount.role, find_by_amount.name)

    assert not any(candidate.role == "button" and candidate.name == "Find Transactions" for candidate in candidates)
    assert candidates[0].css == "#findByAmount"


def test_derive_only_returns_candidates_that_resolve_uniquely(page, pages_url):
    page.goto(f"{pages_url}/transfer.html")
    snapshot = capture(page)
    element = _ref_for(snapshot, "textbox")

    from replaykit.locators.ladder import build_locator

    for candidate in derive(page, element.ref, element.role, element.name):
        assert build_locator(page, candidate).count() == 1


def test_derive_locates_a_table_cell_positionally_not_by_its_own_dynamic_text(page, pages_url):
    """A balance cell's role+name candidate IS the balance ('-$87.50') and the
    nearest text to anchor on is the account number link -- both are the
    discovery user's own data, not stable across other users at replay time.
    Confirmed live: extraction failed for every replay user because neither
    candidate resolved against their different account numbers/balances."""
    page.goto(f"{pages_url}/datatable.html")
    snapshot = capture(page)
    balance_cell = next(
        e for e in snapshot.elements.values() if e.role == "cell" and e.name == "-$87.50"
    )

    candidates = derive(page, balance_cell.ref, balance_cell.role, balance_cell.name)

    assert any(c.css and "accountTable" in c.css for c in candidates)
    assert not any(c.role == "cell" and c.name == "-$87.50" for c in candidates)
    assert not any(c.xpath and "14676" in c.xpath for c in candidates)
    from replaykit.locators.ladder import build_locator
    positional = next(c for c in candidates if c.css and "accountTable" in c.css)
    assert build_locator(page, positional).inner_text() == "-$87.50"


def test_derive_rejects_unique_anchor_candidates_for_a_different_same_tag_sibling(page, pages_url):
    page.goto(f"{pages_url}/sibling_anchor.html")
    second_input = _ref_for(capture(page), "textbox", index=1)

    from replaykit.locators.ladder import build_locator

    candidates = derive(page, second_input.ref, second_input.role, second_input.name)

    assert candidates
    assert all(
        build_locator(page, candidate).evaluate("element => element.id") == "second"
        for candidate in candidates
    )
