"""A local GUI for chip8bit.

Double-clicking the executable starts a tiny web server on the loopback interface
and opens the window in the default browser. Everything is standard library: no
Qt, no Electron, no install step, and the whole UI is one HTML page that ships
inside the executable.

Why a browser window instead of a native toolkit? Drag and drop of files onto a
page, an audio player for the result, and a download button all come for free —
and the same code can be served headlessly (`--serve`) or self-tested (`--selftest`).
"""

import json
import os
import sys
import tempfile
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from . import chips, demo, importers
from .arrange import Options, arrange
from .render import RenderOptions, render, wav_bytes
from .vgmout import write_vgm

MAX_UPLOAD = 64 * 1024 * 1024


class Store:
    """Uploads and rendered results, kept in memory for the life of the session."""

    def __init__(self):
        self.files: Dict[str, dict] = {}
        self.results: Dict[str, dict] = {}
        self.lock = threading.Lock()

    def add_file(self, name: str, data: bytes) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "size": len(data),
            "data": data,
        }
        with self.lock:
            self.files[entry["id"]] = entry
        return entry

    def add_result(self, name: str, data: bytes) -> dict:
        entry = {"id": uuid.uuid4().hex[:12], "name": name, "data": data}
        with self.lock:
            self.results[entry["id"]] = entry
        return entry


def _temp_path(name: str, data: bytes) -> str:
    suffix = os.path.splitext(name)[1] or ".bin"
    handle, path = tempfile.mkstemp(prefix="chip8bit-", suffix=suffix)
    with os.fdopen(handle, "wb") as out:
        out.write(data)
    return path


def _clean_label(extensions: List[str]) -> str:
    return "nes" if not extensions else "nes+" + "+".join(extensions)


def convert(name: str, data: bytes, settings: dict, store: Store) -> dict:
    """Run one file through the whole pipeline; returns the JSON the page needs."""
    extensions = [e for e in settings.get("extensions", [])
                  if e in chips.EXTENSION_CHANNELS]
    channels = chips.build_channel_set(extensions)

    path = _temp_path(name, data)
    try:
        importer = importers.find_for(path)
        song = importer(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if not song.notes:
        return {"ok": False, "error": "; ".join(song.warnings) or
                "no notes found in this file"}

    options = Options(
        allow_sharing=bool(settings.get("sharing", True)),
        arp_frames=int(settings.get("arp_frames", 2) or 2),
        quantize=bool(settings.get("quantize", True)),
    )
    notes, stats = arrange(song, channels, options)

    render_options = RenderOptions(
        rate=int(settings.get("rate", 44100) or 44100),
        bits=16 if int(settings.get("bits", 8) or 8) == 16 else 8,
        stereo=bool(settings.get("stereo", False)),
        gain=float(settings.get("gain", 0.9) or 0.9),
    )

    grouped: Dict[str, List] = {}
    for note in notes:
        grouped.setdefault(note.channel, []).append(note)

    pcm, _stems, duration = render(notes, channels, render_options, grouped)
    audio = wav_bytes(pcm, render_options)

    stem = os.path.splitext(name)[0]
    out_name = "%s [%s].wav" % (stem, _clean_label(extensions))
    result = store.add_result(out_name, audio)

    payload = {
        "ok": True,
        "id": result["id"],
        "name": out_name,
        "seconds": round(duration, 2),
        "bytes": len(audio),
        "bits": render_options.bits,
        "rate": render_options.rate,
        "stereo": render_options.stereo,
        "voices": len(stats.per_channel_notes),
        "channels": stats.per_channel_notes,
        "placed": stats.direct,
        "rehomed": stats.overflow,
        "shared": stats.shared,
        "dropped": stats.dropped,
        "clusters": stats.clusters,
        "warnings": song.warnings,
        "source": song.source_format,
    }

    if settings.get("export_vgm"):
        vgm = store.add_result(os.path.splitext(out_name)[0] + ".vgm", b"")
        vgm_path = _temp_path(".vgm", b"")
        try:
            messages = write_vgm(vgm_path, notes, channels, duration, extensions)
            with open(vgm_path, "rb") as handle:
                vgm["data"] = handle.read()
        finally:
            try:
                os.unlink(vgm_path)
            except OSError:
                pass
        payload["vgm"] = {"id": vgm["id"], "name": vgm["name"],
                          "warnings": messages}

    return payload


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>chip8bit — NES / 8-bit transcoder</title>
<style>
:root {
  color-scheme: dark;
  --bg:#0d1117; --panel:#161b22; --panel2:#1c2430; --line:#2a3542;
  --text:#e6edf3; --muted:#8b98a5; --accent:#6ee7b7; --accent2:#38bdf8;
  --warn:#fbbf24; --bad:#f87171;
}
* { box-sizing:border-box; }
body {
  margin:0; font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  background:radial-gradient(1200px 600px at 10% -10%,#172436 0%,var(--bg) 55%);
  color:var(--text); min-height:100vh;
}
header {
  display:flex; align-items:baseline; gap:14px; padding:20px 26px 14px;
  border-bottom:1px solid var(--line); flex-wrap:wrap;
}
h1 { font-size:22px; margin:0; letter-spacing:.5px; }
h1 span { color:var(--accent); }
.tagline { color:var(--muted); font-size:13px; }
.badge {
  margin-left:auto; background:#0f2b23; color:var(--accent); border:1px solid #1f5c48;
  padding:4px 12px; border-radius:999px; font-size:13px; font-weight:600;
}
main {
  display:grid; gap:18px; padding:18px 26px 40px;
  grid-template-columns:minmax(280px,1fr) minmax(300px,1.05fr) minmax(320px,1.1fr);
}
@media (max-width:1100px){ main{ grid-template-columns:1fr; } }
section.panel {
  background:var(--panel); border:1px solid var(--line); border-radius:14px;
  padding:16px; display:flex; flex-direction:column; gap:12px; min-height:200px;
}
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.12em;
     color:var(--muted); margin:0; }
.dropzone {
  border:2px dashed #2f3d4d; border-radius:12px; padding:22px 14px; text-align:center;
  color:var(--muted); cursor:pointer; transition:.15s; background:#11161d;
}
.dropzone:hover, .dropzone.hot { border-color:var(--accent); color:var(--text);
  background:#12211c; }
.dropzone b { color:var(--text); }
ul.list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:8px; }
ul.list li {
  display:flex; align-items:center; gap:10px; background:var(--panel2);
  border:1px solid var(--line); border-radius:10px; padding:9px 11px; font-size:13px;
}
ul.list li .name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
ul.list li .meta { color:var(--muted); font-size:12px; }
button {
  font:inherit; border-radius:9px; border:1px solid var(--line); background:#212b36;
  color:var(--text); padding:9px 14px; cursor:pointer; transition:.15s;
}
button:hover:not(:disabled) { border-color:var(--accent); }
button:disabled { opacity:.45; cursor:default; }
button.primary {
  background:linear-gradient(180deg,#2ee6a6,#17b98a); color:#04231a; font-weight:700;
  border:none; padding:13px 18px; font-size:15px;
}
button.primary:hover:not(:disabled){ filter:brightness(1.06); }
button.ghost { background:transparent; }
button.tiny { padding:5px 9px; font-size:12px; border-radius:7px; }
.chip {
  display:flex; gap:10px; align-items:flex-start; padding:10px 12px; border-radius:11px;
  border:1px solid var(--line); background:var(--panel2); cursor:pointer;
  transition:.15s; user-select:none;
}
.chip:hover { border-color:#3c4c5e; }
.chip.on { border-color:var(--accent); background:#10241d; }
.chip.locked { opacity:.75; cursor:default; border-style:dashed; }
.chip .dot { width:10px; height:10px; border-radius:50%; background:#39485a;
  margin-top:5px; flex:none; }
.chip.on .dot { background:var(--accent); box-shadow:0 0 10px var(--accent); }
.chip b { font-size:13px; }
.chip small { color:var(--muted); display:block; font-size:12px; }
.row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
label.field { display:flex; flex-direction:column; gap:4px; font-size:12px;
  color:var(--muted); }
label.check { display:flex; align-items:center; gap:7px; font-size:12.5px;
  color:var(--muted); cursor:pointer; }
label.check input { accent-color:var(--accent); width:15px; height:15px; }
select, input[type=number] {
  font:inherit; background:#10161d; color:var(--text); border:1px solid var(--line);
  border-radius:8px; padding:7px 9px;
}
details summary { cursor:pointer; color:var(--muted); font-size:12px; }
.result { border:1px solid var(--line); border-radius:12px; padding:12px;
  background:var(--panel2); display:flex; flex-direction:column; gap:9px; }
.result .head { display:flex; gap:8px; align-items:center; }
.result .head .name { font-weight:600; flex:1; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
.result audio { width:100%; height:34px; }
.statline { font-size:12px; color:var(--muted); }
.statline b { color:var(--text); font-weight:600; }
table.chans { width:100%; border-collapse:collapse; font-size:12px; }
table.chans td { padding:2px 4px; border-bottom:1px solid #232d38; }
table.chans td:last-child { text-align:right; color:var(--accent2); }
.log { font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; color:var(--muted);
  background:#0c1218; border:1px solid var(--line); border-radius:10px; padding:10px;
  max-height:190px; overflow:auto; white-space:pre-wrap; }
.spinner { display:inline-block; width:13px; height:13px; border:2px solid #2b3a4a;
  border-top-color:var(--accent); border-radius:50%; animation:spin .7s linear infinite;
  vertical-align:-2px; margin-right:7px; }
@keyframes spin { to { transform:rotate(360deg); } }
.warn { color:var(--warn); font-size:12px; }
.err { color:var(--bad); font-size:13px; }
footer { color:#5f6b78; font-size:12px; padding:0 26px 26px; }
footer a { color:#7f8b98; }
</style>
</head>
<body>
<header>
  <h1>chip<span>8</span>bit</h1>
  <span class="tagline">MIDI &amp; Genesis game music &rarr; NES 8-bit, with extension chips</span>
  <span class="badge" id="voices">4 voices</span>
</header>

<main>
  <section class="panel">
    <h2>1 &middot; Add music</h2>
    <div class="dropzone" id="drop">
      <b>Drop files here</b><br>
      <small>.mid .midi .rmi .kar .vgm .vgz .gym .zip</small>
    </div>
    <input type="file" id="picker" multiple hidden>
    <ul class="list" id="queue"></ul>
    <div class="row">
      <button class="ghost tiny" id="demo">Load the demo tune</button>
      <button class="ghost tiny" id="clear">Clear list</button>
    </div>
  </section>

  <section class="panel">
    <h2>2 &middot; Pick chips</h2>
    <div id="chip-list" style="display:flex;flex-direction:column;gap:8px"></div>
    <details>
      <summary>Advanced</summary>
      <div class="row" style="margin-top:10px">
        <label class="field">Bit depth
          <select id="bits"><option value="8">8-bit (authentic)</option>
            <option value="16">16-bit (cleaner)</option></select></label>
        <label class="field">Sample rate
          <select id="rate"><option>44100</option><option>48000</option>
            <option>22050</option></select></label>
        <label class="field">Arpeggio step
          <select id="arp"><option value="2">2 frames</option>
            <option value="1">1 frame (fast)</option><option value="3">3 frames</option></select></label>
      </div>
      <div class="row" style="margin-top:10px;gap:16px">
        <label class="check"><input type="checkbox" id="stereo"> stereo output</label>
        <label class="check"><input type="checkbox" id="sharing" checked>
          share a channel as an arpeggio when it is full</label>
        <label class="check"><input type="checkbox" id="vgm"> also write a .vgm log</label>
      </div>
    </details>
  </section>

  <section class="panel">
    <h2>3 &middot; Convert</h2>
    <button class="primary" id="convert" disabled>Convert</button>
    <div id="status" class="statline"></div>
    <div id="results" style="display:flex;flex-direction:column;gap:10px"></div>
    <div class="log" id="log" hidden></div>
  </section>
</main>

<footer>
  <span>Long songs take a few seconds per minute of audio. Everything happens on
  this machine; nothing is uploaded anywhere.</span>
  <button class="tiny ghost" id="quit" style="float:right">Quit chip8bit</button>
</footer>

<script>
const state = { files: [], chips: [], selected: new Set() };
const $ = (id) => document.getElementById(id);
const human = (n) => n > 1048576 ? (n/1048576).toFixed(1)+" MB"
                  : n > 1024 ? Math.round(n/1024)+" KB" : n+" B";

function logLine(text) {
  const box = $("log");
  box.hidden = false;
  box.textContent += text + "\n";
  box.scrollTop = box.scrollHeight;
}

function renderVoices() {
  let count = 4;
  state.chips.forEach(c => { if (c.extension && state.selected.has(c.extension)) count += c.channels; });
  $("voices").textContent = count + " voices";
}

async function loadChips() {
  const data = await (await fetch("api/chips")).json();
  state.chips = data.chips;
  const list = $("chip-list");
  data.chips.forEach(chip => {
    const el = document.createElement("div");
    el.className = "chip" + (chip.extension ? "" : " on locked");
    el.innerHTML = `<span class="dot"></span><span><b>${chip.label}</b>
      <small>${chip.description}</small></span>`;
    if (!chip.extension) { el.classList.add("on"); }
    else {
      el.onclick = () => {
        if (state.selected.has(chip.extension)) state.selected.delete(chip.extension);
        else state.selected.add(chip.extension);
        el.classList.toggle("on");
        renderVoices();
        remember();
      };
    }
    list.appendChild(el);
    if (chip.extension && state.selected.has(chip.extension)) el.classList.add("on");
  });
  renderVoices();
}

function renderQueue() {
  const list = $("queue");
  list.innerHTML = "";
  state.files.forEach((file, index) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="name" title="${file.name}">${file.name}</span>
      <span class="meta">${human(file.size)}</span>`;
    const remove = document.createElement("button");
    remove.className = "tiny ghost"; remove.textContent = "✕";
    remove.onclick = () => { state.files.splice(index, 1); renderQueue(); };
    li.appendChild(remove);
    list.appendChild(li);
  });
  $("convert").disabled = state.files.length === 0;
}

async function upload(file) {
  const response = await fetch("api/upload?name=" + encodeURIComponent(file.name),
    { method: "POST", body: file });
  if (!response.ok) { logLine("upload failed: " + await response.text()); return; }
  const entry = await response.json();
  state.files.push(entry);
  renderQueue();
}

function addFiles(files) {
  [...files].forEach(file => upload(file).catch(e => logLine(String(e))));
}

$("drop").onclick = () => $("picker").click();
$("picker").onchange = (event) => { addFiles(event.target.files); event.target.value = ""; };
["dragenter","dragover"].forEach(type => $("drop").addEventListener(type, (event) => {
  event.preventDefault(); $("drop").classList.add("hot");
}));
["dragleave","drop"].forEach(type => $("drop").addEventListener(type, (event) => {
  event.preventDefault(); $("drop").classList.remove("hot");
}));
$("drop").addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => e.preventDefault());

$("clear").onclick = () => { state.files = []; renderQueue(); };

$("demo").onclick = async () => {
  const response = await fetch("api/demo", { method: "POST" });
  const entry = await response.json();
  state.files.push(entry); renderQueue();
};

function settings() {
  return {
    extensions: [...state.selected],
    bits: parseInt($("bits").value, 10),
    rate: parseInt($("rate").value, 10),
    arp_frames: parseInt($("arp").value, 10),
    stereo: $("stereo").checked,
    sharing: $("sharing").checked,
    export_vgm: $("vgm").checked,
  };
}

function remember() {
  try {
    localStorage.setItem("chip8bit", JSON.stringify({
      chips: [...state.selected],
      bits: $("bits").value, rate: $("rate").value, arp: $("arp").value,
      stereo: $("stereo").checked, sharing: $("sharing").checked,
      vgm: $("vgm").checked,
    }));
  } catch (error) { /* a browser with storage disabled still works */ }
}

function restore() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("chip8bit") || "null"); } catch (e) {}
  if (!saved) return;
  (saved.chips || []).forEach(name => state.selected.add(name));
  if (saved.bits) $("bits").value = saved.bits;
  if (saved.rate) $("rate").value = saved.rate;
  if (saved.arp) $("arp").value = saved.arp;
  $("stereo").checked = !!saved.stereo;
  if (saved.sharing === false) $("sharing").checked = false;
  $("vgm").checked = !!saved.vgm;
}

function resultCard(data) {
  const card = document.createElement("div");
  card.className = "result";
  const bits = data.bits + "-bit";
  const channelRows = Object.entries(data.channels).sort()
    .map(([name, count]) => `<tr><td>${name}</td><td>${count}</td></tr>`).join("");
  card.innerHTML = `
    <div class="head">
      <span class="name" title="${data.name}">${data.name}</span>
      <a class="tiny" href="api/file/${data.id}?download=1"
         download="${data.name}"><button class="tiny">Download</button></a>
    </div>
    <audio controls src="api/file/${data.id}"></audio>
    <div class="statline">
      <b>${data.voices}</b> voices &middot; <b>${data.seconds}s</b> &middot; ${bits}
      @ ${(data.rate/1000)} kHz &middot; <b>${data.placed}</b> placed,
      <b>${data.rehomed}</b> on spare channels, <b>${data.shared}</b> shared,
      <b>${data.dropped}</b> dropped
    </div>
    <details><summary>Channel map</summary>
      <table class="chans">${channelRows}</table></details>`;
  if (data.warnings && data.warnings.length) {
    const warn = document.createElement("div");
    warn.className = "warn";
    warn.textContent = data.warnings.join(" · ");
    card.appendChild(warn);
  }
  if (data.vgm) {
    const link = document.createElement("a");
    link.href = "api/file/" + data.vgm.id + "?download=1";
    link.innerHTML = `<button class="tiny">Download ${data.vgm.name}</button>`;
    card.appendChild(link);
  }
  return card;
}

$("convert").onclick = async () => {
  const queue = [...state.files];
  const config = settings();
  $("convert").disabled = true;
  $("results").innerHTML = "";
  $("log").hidden = true;
  $("log").textContent = "";

  for (let index = 0; index < queue.length; index++) {
    const file = queue[index];
    $("status").innerHTML = `<span class="spinner"></span>Converting ` +
      `<b>${file.name}</b> (${index + 1}/${queue.length})…`;
    try {
      const response = await fetch("api/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: file.id, settings: config }),
      });
      const data = await response.json();
      if (!data.ok) {
        const error = document.createElement("div");
        error.className = "err";
        error.textContent = `${file.name}: ${data.error}`;
        $("results").prepend(error);
      } else {
        $("results").prepend(resultCard(data));
        logLine(`${file.name} → ${data.voices} voices, ${data.seconds}s`);
        Object.entries(data.channels).forEach(([channel, count]) =>
          logLine(`   ${channel.padEnd(12)} ${count} notes`));
      }
    } catch (error) {
      const failure = document.createElement("div");
      failure.className = "err";
      failure.textContent = `${file.name}: ${error}`;
      $("results").prepend(failure);
    }
  }
  state.files = [];
  renderQueue();
  $("status").textContent = "Done. Drop more files to convert again.";
};

$("quit").onclick = async () => {
  await fetch("api/quit", { method: "POST" });
  document.body.innerHTML = '<div style="padding:60px;text-align:center;' +
    'font:16px system-ui;color:#8b98a5">chip8bit has stopped. You can close this tab.</div>';
};

document.querySelectorAll("#bits, #rate, #arp, #stereo, #sharing, #vgm")
  .forEach(input => input.addEventListener("change", remember));

async function loadDroppedOnExe() {
  const add = new URLSearchParams(location.search).get("add");
  if (!add) return;
  for (const id of add.split(",").filter(Boolean)) {
    try {
      const entry = await (await fetch("api/entry/" + id)).json();
      if (entry.id) state.files.push(entry);
    } catch (error) { /* ignore a stale link */ }
  }
  renderQueue();
  history.replaceState({}, "", location.pathname);
}

restore();
loadChips();
loadDroppedOnExe();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "chip8bit"

    # keep the console quiet: a GUI app should not chatter in a terminal
    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------------ helpers
    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body, status=200, content_type="text/plain; charset=utf-8"):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > MAX_UPLOAD:
            raise ValueError("that file is too large")
        return self.rfile.read(length)

    @property
    def store(self) -> Store:
        return self.server.store           # type: ignore[attr-defined]

    # --------------------------------------------------------------------- pages
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route in ("/", "/index.html"):
            self._text(PAGE, content_type="text/html; charset=utf-8")
            return

        if route.startswith("/api/entry/"):
            entry = self.store.files.get(route.rsplit("/", 1)[-1])
            if entry is None:
                self._json({"ok": False, "error": "unknown file"}, 404)
                return
            self._json({"id": entry["id"], "name": entry["name"],
                        "size": entry["size"]})
            return

        if route == "/api/chips":
            self._json({"chips": _chip_metadata()})
            return

        if route.startswith("/api/file/"):
            identifier = route.rsplit("/", 1)[-1]
            entry = self.store.results.get(identifier)
            if entry is None:
                self._json({"ok": False, "error": "unknown result"}, 404)
                return
            download = parse_qs(parsed.query).get("download")
            body = entry["data"]
            self.send_response(200)
            content_type = ("audio/wav" if entry["name"].endswith(".wav")
                            else "application/octet-stream")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if download:
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % entry["name"])
            self.end_headers()
            self.wfile.write(body)
            return

        if route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self._json({"ok": False, "error": "not found"}, 404)

    # ------------------------------------------------------------------ commands
    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route == "/api/upload":
                name = (parse_qs(parsed.query).get("name") or ["music.bin"])[0]
                data = self._body()
                entry = self.store.add_file(os.path.basename(name), data)
                self._json({"id": entry["id"], "name": entry["name"],
                            "size": entry["size"]})
                return

            if route == "/api/demo":
                data = demo.build()
                entry = self.store.add_file("demo tune.mid", data)
                self._json({"id": entry["id"], "name": entry["name"],
                            "size": entry["size"]})
                return

            if route == "/api/convert":
                request = json.loads(self._body() or b"{}")
                entry = self.store.files.get(request.get("id", ""))
                if entry is None:
                    self._json({"ok": False, "error": "that file is no longer queued"}, 400)
                    return
                payload = convert(entry["name"], entry["data"],
                                  request.get("settings", {}), self.store)
                self._json(payload)
                return

            if route == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            self._json({"ok": False, "error": "not found"}, 404)
        except Exception as error:                       # never kill the window
            self._json({"ok": False, "error": "%s: %s" % (type(error).__name__, error)}, 500)


def _log_path() -> str:
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else tempfile.gettempdir())
    return os.path.join(base, "chip8bit.log")


def _say(text: str) -> None:
    """print() that survives a windowed build, where sys.stdout is None."""
    stream = sys.stdout
    if stream is not None:
        try:
            stream.write(text + "\n")
            stream.flush()
            return
        except Exception:
            pass
    try:
        with open(_log_path(), "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def _report_fatal(text: str) -> None:
    """A windowed executable has no console: leave a log and a dialog instead."""
    try:
        with open(_log_path(), "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "chip8bit", 0x10)
            return
        except Exception:
            pass
    _say(text)


def _chip_metadata() -> List[dict]:
    metadata = [{
        "extension": "",
        "label": "NES base console",
        "channels": 4,
        "description": "pulse1, pulse2, triangle, noise — always on",
    }]
    descriptions = {
        "vrc6": "Konami VRC6 — two extra pulses and a sawtooth",
        "mmc5": "Nintendo MMC5 — two clean extra pulses",
        "fds": "Famicom Disk System — one wavetable voice",
        "n163": "Namco 163 — eight wavetable voices",
        "psg": "SN76489 — three squares, the Genesis chip's own sound",
        "dmc": "APU delta channel — an extra percussion voice",
    }
    for name, specs in chips.EXTENSION_CHANNELS.items():
        metadata.append({
            "extension": name,
            "label": "%s  (+%d)" % (name.upper(), len(specs)),
            "channels": len(specs),
            "description": descriptions.get(name, ", ".join(s.id for s in specs)),
        })
    return metadata


def make_server(host: str = "127.0.0.1", port: int = 8734) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.store = Store()                 # type: ignore[attr-defined]
    server.daemon_threads = True
    return server


def selftest(host: str = "127.0.0.1") -> int:
    """Start the app, drive it over HTTP, and check a real conversion."""
    import urllib.request

    server = make_server(host, 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % port
    failures = []

    def check(label, condition, detail=""):
        _say(("  ok   " if condition else "  FAIL ") + label
             + (" " + detail if not condition else ""))
        if not condition:
            failures.append(label)

    try:
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode()
        check("page served", "chip8bit" in page and "<audio controls" in page)

        chip_list = json.loads(urllib.request.urlopen(base + "/api/chips", timeout=10).read())
        check("chip metadata", len(chip_list["chips"]) == 7,
              str(len(chip_list["chips"])))

        request = urllib.request.Request(base + "/api/demo", data=b"", method="POST")
        entry = json.loads(urllib.request.urlopen(request, timeout=10).read())
        check("demo tune generated", entry.get("size", 0) > 500, str(entry))

        body = json.dumps({
            "id": entry["id"],
            "settings": {"extensions": ["vrc6", "mmc5", "fds", "n163", "psg", "dmc"],
                         "bits": 8, "rate": 44100, "arp_frames": 2},
        }).encode()
        request = urllib.request.Request(base + "/api/convert", data=body,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
        result = json.loads(urllib.request.urlopen(request, timeout=120).read())
        check("conversion succeeded", result.get("ok") is True, str(result)[:200])
        if result.get("ok"):
            check("all channels used", result.get("voices", 0) >= 10,
                  str(result.get("voices")))
            check("nothing dropped", result.get("dropped") == 0)
            wav = urllib.request.urlopen(base + "/api/file/" + result["id"], timeout=30).read()
            check("wav served", wav[:4] == b"RIFF" and len(wav) > 100000,
                  "%d bytes" % len(wav))

        # a second pass with the VGM log switched on exercises that code path too
        body = json.dumps({
            "id": entry["id"],
            "settings": {"extensions": ["dmc", "vrc6"], "bits": 16,
                         "export_vgm": True, "sharing": False},
        }).encode()
        request = urllib.request.Request(base + "/api/convert", data=body,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
        second = json.loads(urllib.request.urlopen(request, timeout=120).read())
        check("conversion with a vgm log succeeded", second.get("ok") is True,
              str(second)[:200])
        if second.get("ok"):
            check("vgm offered for download", bool(second.get("vgm")))
            if second.get("vgm"):
                vgm = urllib.request.urlopen(
                    base + "/api/file/" + second["vgm"]["id"], timeout=30).read()
                check("vgm served", vgm[:4] == b"Vgm ", str(vgm[:8]))

        request = urllib.request.Request(base + "/api/quit", data=b"", method="POST")
        urllib.request.urlopen(request, timeout=10).read()
    finally:
        server.shutdown()

    _say("%d GUI check(s) failed" % len(failures))
    return 0 if not failures else 1


def run(host: str = "127.0.0.1", port: int = 8734, open_browser: bool = True,
        initial_files: Optional[List[str]] = None) -> int:
    try:
        try:
            server = make_server(host, port)
        except OSError:
            server = make_server(host, 0)      # port taken: take any free one
    except Exception as error:
        _report_fatal("chip8bit could not start its window: %s: %s"
                      % (type(error).__name__, error))
        return 1

    actual = server.server_address[1]
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = "http://%s:%d/" % (shown_host, actual)

    # files dropped onto the executable arrive as arguments: queue them up
    queued = []
    for path in initial_files or []:
        try:
            with open(path, "rb") as handle:
                entry = server.store.add_file(os.path.basename(path), handle.read())
            queued.append(entry["id"])
        except OSError as error:
            _say("skipped %s (%s)" % (path, error))
    if queued:
        url += "?add=" + ",".join(queued)

    _say("chip8bit window: %s" % url)
    _say("Quit from the page when you are done.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0
