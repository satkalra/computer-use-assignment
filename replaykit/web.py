import threading

from flask import Flask, Response, jsonify, request

from replaykit.control import ControlState


_DASHBOARD_HTML = """<!doctype html>
<html><head><title>replaykit operator</title></head>
<body>
<h1>replaykit run status</h1>
<pre id="status">loading...</pre>
<img id="shot" style="max-width: 800px; display: none">
<button id="resume" style="display: none" onclick="decide('resume')">Resume</button>
<button id="abort" style="display: none" onclick="decide('abort')">Abort</button>
<script>
async function poll() {
  const res = await fetch('/status');
  const data = await res.json();
  document.getElementById('status').textContent = JSON.stringify(data, null, 2);
  const waiting = data.owner === 'human';
  document.getElementById('resume').style.display = waiting ? 'inline' : 'none';
  document.getElementById('abort').style.display = waiting ? 'inline' : 'none';
  const shot = document.getElementById('shot');
  if (data.request && data.request.screenshot_base64) {
    shot.src = 'data:image/png;base64,' + data.request.screenshot_base64;
    shot.style.display = 'block';
  } else {
    shot.style.display = 'none';
  }
}
async function decide(value) {
  await fetch('/decision', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({decision: value}),
  });
}
setInterval(poll, 1000);
poll();
</script>
</body></html>"""


def create_app(control: ControlState) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def dashboard():
        return Response(_DASHBOARD_HTML, mimetype="text/html")

    @app.get("/status")
    def status():
        return jsonify({"owner": control.owner, "request": control.request})

    @app.post("/decision")
    def decision():
        value = (request.get_json(force=True) or {}).get("decision")
        if value not in {"resume", "abort"}:
            return jsonify({"error": "decision must be 'resume' or 'abort'"}), 400
        control.decision = value
        return jsonify({"ok": True})

    return app


def serve_in_background(control: ControlState, port: int) -> threading.Thread:
    app = create_app(control)
    thread = threading.Thread(
        target=lambda: app.run(port=port, use_reloader=False),
        daemon=True,
    )
    thread.start()
    return thread
