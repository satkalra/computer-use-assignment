from replaykit.recording.schema import Flow, State
from replaykit.replayer.recovery import recover


# --- dialog-dismiss rule: exercised with plain Locator-interface fakes, no browser needed ---

class Button:
    def __init__(self, name):
        self.name = name
        self.clicked = 0

    def click(self):
        self.clicked += 1


class RoleQuery:
    """A get_by_role() result: one matching button, or none."""

    def __init__(self, button):
        self._button = button

    def count(self):
        return 1 if self._button else 0

    def click(self):
        self._button.click()


class Dialog:
    def __init__(self, button):
        self._button = button

    def is_visible(self):
        return True

    def get_by_role(self, role, name=None):
        assert role == "button"
        matched = self._button if (name is None or name.search(self._button.name)) else None
        return RoleQuery(matched)


class DialogLocator:
    def __init__(self, dialog):
        self._dialog = dialog

    def count(self):
        return 1 if self._dialog else 0

    def is_visible(self):
        return self._dialog is not None

    @property
    def first(self):
        return self._dialog


class FakePage:
    def __init__(self, dialog=None):
        self._dialog = dialog

    def locator(self, selector):
        assert selector == "[role=dialog]"
        return DialogLocator(self._dialog)


def flow_with(recovery, states=None):
    default_states = {"login_page": State("login_page", r"/login\.htm", "- heading Login")}
    return Flow("login", 1, {}, states or default_states, [], recovery)


def dialog_rule(name_pattern):
    return {"when": {"aria": "- dialog"}, "do": [{"action": "click", "target": [{"role": "button", "name": name_pattern}]}]}


def state_rule(state_name):
    return {"when": {"state": state_name}, "do": [{"handoff": "session_expired"}]}


def test_recover_clicks_the_dismiss_button_named_by_the_recording_not_a_hardcoded_pattern():
    dismiss = Button("Close notice")
    page = FakePage(dialog=Dialog(dismiss))
    flow = flow_with([dialog_rule("/close notice/i")])

    result = recover(page, flow)

    assert result.dialog_dismissed is True
    assert dismiss.clicked == 1


def test_recover_does_not_dismiss_when_recording_declares_a_different_button_name():
    dismiss = Button("Close notice")
    page = FakePage(dialog=Dialog(dismiss))
    flow = flow_with([dialog_rule("/acknowledge/i")])

    result = recover(page, flow)

    assert result.dialog_dismissed is False
    assert dismiss.clicked == 0


def test_recover_ignores_a_state_rule_that_does_not_declare_a_handoff_action():
    page = FakePage()
    recovery = [{"when": {"state": "login_page"}, "do": [{"action": "click", "target": [{"role": "button", "name": "Retry"}]}]}]
    flow = flow_with(recovery)

    result = recover(page, flow)

    assert result.session_expired is False


# --- session-expiry rule: reuses states.predicate.matches(), so it needs a real page ---

def test_recover_detects_session_expiry_against_the_state_name_the_recording_declares(page, pages_url):
    """The old implementation hardcoded the literal state name 'login_page'. A recording
    that names its login state differently must still be detected correctly."""
    page.goto(f"{pages_url}/login.html")
    states = {"signin": State("signin", r"/login\.html", '- heading "Customer Login"')}
    flow = flow_with([state_rule("signin")], states=states)

    result = recover(page, flow)

    assert result.session_expired is True


def test_recover_reports_no_session_expiry_when_current_page_does_not_match_the_declared_state(page, pages_url):
    page.goto(f"{pages_url}/overview.html")
    states = {"login_page": State("login_page", r"/login\.html", '- heading "Customer Login"')}
    flow = flow_with([state_rule("login_page")], states=states)

    result = recover(page, flow)

    assert result.session_expired is False
