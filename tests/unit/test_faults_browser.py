from replaykit.harness.faults import strip_ids


def test_strip_ids_removes_ids_from_the_loaded_document(page, pages_url):
    strip_ids(page)

    page.goto(f"{pages_url}/login.html")

    assert page.locator("[id]").count() == 0
