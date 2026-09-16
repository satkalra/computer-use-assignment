from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


def _customer_exists(base_url: str, username: str, password: str) -> bool:
    endpoint = f"{base_url.rstrip('/')}/services/bank/login/{quote(username, safe='')}/{quote(password, safe='')}"
    try:
        with urlopen(endpoint, timeout=10) as response:
            return response.status == 200
    except HTTPError:
        return False


def _register(base_url: str, credentials: Credentials) -> None:
    fields = {
        "customer.firstName": "Replaykit",
        "customer.lastName": credentials.username.rsplit("-", 1)[-1],
        "customer.address.street": "1 Test Way",
        "customer.address.city": "Testville",
        "customer.address.state": "TS",
        "customer.address.zipCode": "10001",
        "customer.phoneNumber": "5555550100",
        "customer.ssn": "999-99-9999",
        "customer.username": credentials.username,
        "customer.password": credentials.password,
        "repeatedPassword": credentials.password,
    }
    registration_url = f"{base_url.rstrip('/')}/register.htm"
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(registration_url, timeout=15) as response:
        response.read()
    request = Request(
        registration_url,
        data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with opener.open(request, timeout=15) as response:
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"ParaBank registration failed for {credentials.username}: HTTP {response.status}")
        if b"Your account was created successfully" not in body:
            raise RuntimeError(f"ParaBank registration did not confirm {credentials.username}")


def seed_users(base_url: str, count: int = 10) -> list[Credentials]:
    """Return deterministic credentials, registering each missing user once."""
    if count <= 0:
        raise ValueError("count must be positive")
    users = [Credentials(f"replaykit-user-{index:02d}", "ReplaykitPass1!") for index in range(1, count + 1)]
    for credentials in users:
        if not _customer_exists(base_url, credentials.username, credentials.password):
            _register(base_url, credentials)
    return users
