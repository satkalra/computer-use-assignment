# Prerequisites

Everything replaykit's tests need outside of Python packages.

## ParaBank

The `slow` test suite drives a real browser against a live ParaBank instance.

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts ParaBank on `http://localhost:9099/parabank` (overridable via the
`PARABANK_URL` env var). The compose healthcheck waits for the app to actually
be serving before it reports healthy — give it ~30-60s on first pull.

Check it's up:

```bash
docker compose -f docker/docker-compose.yml ps
curl -f http://localhost:9099/parabank/index.htm
```

## Anthropic API key

Recorder tests that call the model (`tests/integration/test_recorder_end_to_end.py`)
need `ANTHROPIC_API_KEY`. Without it they skip cleanly rather than fail:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

## Python environment

```bash
pip install -r requirements.txt
playwright install chromium
```

## Running the tests

```bash
python -m pytest -q -m "not slow"          # no browser, no ParaBank, no API key
python -m pytest -q -m slow                # needs ParaBank; LLM cases skip without a key
```
