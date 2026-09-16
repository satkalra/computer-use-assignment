from replaykit.recorder.snapshot import capture, locator_for


def test_capture_indexes_named_and_unnamed_elements_by_ref(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    snapshot = capture(page)

    textboxes = [e for e in snapshot.elements.values() if e.role == "textbox"]
    buttons = [e for e in snapshot.elements.values() if e.role == "button"]
    assert len(textboxes) == 2
    assert all(e.name == "" for e in textboxes)
    assert [b.name for b in buttons] == ["Log In"]


def test_locator_for_resolves_a_ref_to_exactly_one_element(page, pages_url):
    page.goto(f"{pages_url}/login.html")
    snapshot = capture(page)
    ref = next(e.ref for e in snapshot.elements.values() if e.role == "button")

    locator = locator_for(page, ref)

    assert locator.count() == 1
    assert locator.inner_text() == "Log In"


def test_capture_records_the_page_url(page, pages_url):
    page.goto(f"{pages_url}/login.html")

    assert capture(page).url.endswith("/login.html")


def test_prune_drops_navigation_chrome(page, pages_url):
    page.goto(f"{pages_url}/chrome.html")

    pruned = capture(page, prune=True).text
    full = capture(page, prune=False).text

    assert "Site Map" in full
    assert "Site Map" not in pruned
    assert "Customer Login" in pruned
