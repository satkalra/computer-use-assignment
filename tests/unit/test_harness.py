from replaykit.harness.faults import slow_response, strip_ids
from replaykit.harness.seed import seed_users


class Route:
    def __init__(self):
        self.continued = 0

    def continue_(self):
        self.continued += 1


class Page:
    def __init__(self):
        self.routes = []
        self.scripts = []

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def add_init_script(self, script):
        self.scripts.append(script)


def test_slow_response_installs_a_route_that_continues_the_request():
    page = Page()

    slow_response(page, "**/overview.htm", delay_ms=0)
    route = Route()
    page.routes[0][1](route)

    assert page.routes[0][0] == "**/overview.htm"
    assert route.continued == 1


def test_strip_ids_installs_a_document_start_script():
    page = Page()

    strip_ids(page)

    assert "removeAttribute('id')" in page.scripts[0]


def test_seed_users_registers_only_absent_deterministic_users(monkeypatch):
    registered = []
    monkeypatch.setattr("replaykit.harness.seed._customer_exists", lambda _url, username, _password: username.endswith("02"))
    monkeypatch.setattr("replaykit.harness.seed._register", lambda _url, credentials: registered.append(credentials.username))

    credentials = seed_users("http://bank.example/parabank", count=3)

    assert [item.username for item in credentials] == ["replaykit-user-01", "replaykit-user-02", "replaykit-user-03"]
    assert registered == ["replaykit-user-01", "replaykit-user-03"]
