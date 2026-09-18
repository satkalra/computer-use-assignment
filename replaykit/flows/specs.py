import os

from replaykit.harness.seed import seed_users
from replaykit.recorder.spec import FlowSpec, InputSpec, OutputSpec


BASE_URL = os.environ.get("PARABANK_URL", "http://localhost:9099/parabank")
CREDENTIAL = {
    "username": InputSpec("string", secret=True),
    "password": InputSpec("string", secret=True),
}


def _fresh_user() -> dict[str, str]:
    """Provide a seeded account before each destructive promotion replay.

    run_gate() uses this return value as the *entire* inputs dict for a
    replay -- it doesn't merge it with anything else -- so every input a
    reset-hooked flow declares has to come from here, not just the
    credentials. TRANSFER_FUNDS declares "amount" too.
    """
    credentials = seed_users(BASE_URL, count=30)[-1]
    return {"username": credentials.username, "password": credentials.password, "amount": "1.00"}


ACCOUNTS_OVERVIEW = FlowSpec(
    name="accounts_overview",
    goal="Log in, open Accounts Overview, and extract the first listed account balance.",
    start_url=f"{BASE_URL}/index.htm",
    inputs=dict(CREDENTIAL),
    outputs={"balance": OutputSpec("decimal")},
)

FIND_TRANSACTIONS = FlowSpec(
    name="find_transactions",
    goal="Log in, find transactions by the given amount, and extract the first result amount.",
    start_url=f"{BASE_URL}/index.htm",
    inputs={**CREDENTIAL, "amount": InputSpec("string")},
    outputs={"found_amount": OutputSpec("decimal")},
)

TRANSFER_FUNDS = FlowSpec(
    name="transfer_funds",
    goal="Log in, transfer the given amount between the first two accounts, and extract the confirmed amount.",
    start_url=f"{BASE_URL}/index.htm",
    inputs={**CREDENTIAL, "amount": InputSpec("string")},
    outputs={"confirmed_amount": OutputSpec("decimal")},
    reset=_fresh_user,
)

OPEN_ACCOUNT = FlowSpec(
    name="open_account",
    goal="Log in, open a SAVINGS account funded from the first existing account, and extract its account number.",
    start_url=f"{BASE_URL}/index.htm",
    inputs=dict(CREDENTIAL),
    outputs={"new_account_id": OutputSpec("integer")},
    reset=_fresh_user,
)


ALL_FLOWS = [ACCOUNTS_OVERVIEW, FIND_TRANSACTIONS, TRANSFER_FUNDS, OPEN_ACCOUNT]
