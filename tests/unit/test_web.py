from replaykit.control import ControlState
from replaykit.web import create_app


def test_status_reports_idle_when_no_intervention_is_pending():
    client = create_app(ControlState()).test_client()

    response = client.get("/status")

    assert response.json == {"owner": "agent", "request": None}


def test_status_reports_a_pending_intervention():
    control = ControlState(owner="human", request={"reason": "stuck"})
    client = create_app(control).test_client()

    response = client.get("/status")

    assert response.json == {"owner": "human", "request": {"reason": "stuck"}}


def test_decision_endpoint_sets_the_control_flag():
    control = ControlState()
    client = create_app(control).test_client()

    response = client.post("/decision", json={"decision": "resume"})

    assert response.status_code == 200
    assert control.decision == "resume"


def test_decision_endpoint_rejects_an_invalid_value():
    control = ControlState()
    client = create_app(control).test_client()

    response = client.post("/decision", json={"decision": "sideways"})

    assert response.status_code == 400
    assert control.decision is None


def test_dashboard_page_loads():
    client = create_app(ControlState()).test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"replaykit" in response.data
