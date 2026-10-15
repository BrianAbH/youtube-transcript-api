"""
Transcriptor de YouTube
-----------------------
Pega el link de un video de YouTube y obtén su transcripción.

Uso web:   python app.py            -> abre http://127.0.0.1:5000
Uso CLI:   python app.py --cli "https://youtu.be/XXXXXXXXXXX" [--lang es] [--timestamps]
"""
import re
import sys
import argparse
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, jsonify, render_template_string
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    """Extrae el ID de 11 caracteres desde distintos formatos de link de YouTube."""
    url = (url or "").strip()
    if VIDEO_ID_RE.match(url):
        return url
    if not re.match(r"^https?://", url):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path_parts = [p for p in parsed.path.split("/") if p]

    candidate = None
    if host == "youtu.be" and path_parts:
        candidate = path_parts[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        elif len(path_parts) >= 2 and path_parts[0] in ("embed", "shorts", "live", "v"):
            candidate = path_parts[1]
    if candidate and VIDEO_ID_RE.match(candidate):
        return candidate
    return None


def fetch_transcript(video_id: str, lang: str = "auto") -> dict:
    """Devuelve idioma, si es autogenerada y la lista de segmentos."""
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    chosen = None
    if lang and lang != "auto":
        try:
            chosen = transcript_list.find_transcript([lang])
        except Exception:
            chosen = None
    if chosen is None:
        # Preferir español, luego inglés, luego lo que haya disponible
        try:
            chosen = transcript_list.find_transcript(["es", "es-419", "en"])
        except Exception:
            chosen = next(iter(transcript_list))

    fetched = chosen.fetch()
    segments = [
        {"start": s.start, "duration": s.duration, "text": s.text.replace("\n", " ")}
        for s in fetched.snippets
    ]
    return {
        "video_id": video_id,
        "language": chosen.language,
        "language_code": chosen.language_code,
        "is_generated": chosen.is_generated,
        "segments": segments,
    }


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "TranscriptsDisabled":
        return "Este video tiene las transcripciones desactivadas."
    if name == "NoTranscriptFound" or name == "StopIteration":
        return "No se encontró una transcripción para este video."
    if name in ("VideoUnavailable", "VideoUnplayable"):
        return "El video no está disponible (privado, eliminado o restringido)."
    if name in ("RequestBlocked", "IpBlocked"):
        return ("YouTube bloqueó la petición desde tu IP (común en servidores/VPN). "
                "Prueba desde tu red doméstica.")
    if name == "AgeRestricted":
        return "El video tiene restricción de edad."
    return f"Error inesperado ({name}): {exc}"


def fmt_ts(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def to_text(segments: list[dict], timestamps: bool) -> str:
    if timestamps:
        return "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segments)
    return " ".join(s["text"] for s in segments)


@app.get("/api/transcript")
def api_transcript():
    url = request.args.get("url", "")
    lang = request.args.get("lang", "auto")
    video_id = extract_video_id(url)
    if not video_id:
        return jsonify(error="El link no parece ser un video válido de YouTube."), 400
    try:
        return jsonify(fetch_transcript(video_id, lang))
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=friendly_error(exc)), 502


PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transcriptor de YouTube</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1b1f24; --muted:#6a7380; --accent:#d92d20; --line:#e3e6ea; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14171a; --card:#1d2125; --ink:#e8eaed; --muted:#9aa3ad; --line:#2d3339; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  main { max-width: 820px; margin: 0 auto; padding: 32px 16px 64px; }
  h1 { font-size: 1.6rem; margin: 0 0 4px; }
  p.sub { color: var(--muted); margin: 0 0 24px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }
  .row { display:flex; gap:8px; flex-wrap:wrap; }
  input[type=text] { flex:1 1 320px; padding:12px; border:1px solid var(--line); border-radius:8px;
                     background:var(--bg); color:var(--ink); font-size:1rem; }
  select, button { padding:12px 14px; border-radius:8px; border:1px solid var(--line);
                   background:var(--card); color:var(--ink); font-size:1rem; cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
  button:disabled { opacity:.6; cursor:wait; }
  label.opt { display:flex; align-items:center; gap:6px; color:var(--muted); font-size:.95rem; margin-top:12px; }
  #status { margin-top:16px; color:var(--muted); }
  #status.error { color:var(--accent); }
  #result { display:none; margin-top:16px; }
  #meta { color:var(--muted); font-size:.9rem; margin-bottom:8px; }
  textarea { width:100%; min-height:380px; padding:12px; border:1px solid var(--line); border-radius:8px;
             background:var(--bg); color:var(--ink); font:15px/1.6 inherit; resize:vertical; }
  .actions { margin-top:8px; display:flex; gap:8px; }
</style>
</head>
<body>
<main>
  <h1>Transcriptor de YouTube</h1>
  <p class="sub">Pega el link de un video y obtén su transcripción.</p>

  <div class="card">
    <form id="form" class="row">
      <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." required autofocus>
      <select id="lang" title="Idioma">
        <option value="auto">Idioma: automático</option>
        <option value="es">Español</option>
        <option value="en">English</option>
        <option value="pt">Português</option>
        <option value="fr">Français</option>
        <option value="de">Deutsch</option>
        <option value="it">Italiano</option>
      </select>
      <button id="go" class="primary" type="submit">Transcribir</button>
    </form>
    <label class="opt"><input id="ts" type="checkbox"> Incluir marcas de tiempo</label>
    <div id="status"></div>

    <div id="result">
      <div id="meta"></div>
      <textarea id="out" readonly></textarea>
      <div class="actions">
        <button id="copy" type="button">Copiar</button>
        <button id="download" type="button">Descargar .txt</button>
      </div>
    </div>
  </div>
</main>

<script>
  const $ = id => document.getElementById(id);
  let data = null;

  const fmt = s => {
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const mm = String(m).padStart(2, '0'), ss = String(sec).padStart(2, '0');
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  };

  function render() {
    if (!data) return;
    $('out').value = $('ts').checked
      ? data.segments.map(s => `[${fmt(s.start)}] ${s.text}`).join('\\n')
      : data.segments.map(s => s.text).join(' ');
  }

  $('ts').addEventListener('change', render);

  $('form').addEventListener('submit', async e => {
    e.preventDefault();
    const status = $('status');
    status.className = ''; status.textContent = 'Obteniendo transcripción…';
    $('result').style.display = 'none';
    $('go').disabled = true;
    try {
      const q = new URLSearchParams({ url: $('url').value, lang: $('lang').value });
      const res = await fetch('/api/transcript?' + q);
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || 'Error desconocido');
      data = json;
      status.textContent = '';
      $('meta').textContent = `Idioma: ${json.language}` +
        (json.is_generated ? ' (autogenerada)' : '') + ` · ${json.segments.length} segmentos`;
      $('result').style.display = 'block';
      render();
    } catch (err) {
      status.className = 'error';
      status.textContent = err.message;
    } finally {
      $('go').disabled = false;
    }
  });

  $('copy').addEventListener('click', async () => {
    await navigator.clipboard.writeText($('out').value);
    $('copy').textContent = '¡Copiado!';
    setTimeout(() => $('copy').textContent = 'Copiar', 1500);
  });

  $('download').addEventListener('click', () => {
    const blob = new Blob([$('out').value], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `transcripcion-${data.video_id}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE)


def run_cli(args):
    video_id = extract_video_id(args.cli)
    if not video_id:
        sys.exit("El link no parece ser un video válido de YouTube.")
    try:
        result = fetch_transcript(video_id, args.lang)
    except Exception as exc:  # noqa: BLE001
        sys.exit(friendly_error(exc))
    print(to_text(result["segments"], args.timestamps))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcriptor de YouTube")
    parser.add_argument("--cli", metavar="URL", help="Imprime la transcripción en la terminal")
    parser.add_argument("--lang", default="auto", help="Código de idioma (es, en, ...)")
    parser.add_argument("--timestamps", action="store_true", help="Incluir marcas de tiempo")
    parsed = parser.parse_args()
    if parsed.cli:
        run_cli(parsed)
    else:
        app.run(host="127.0.0.1", port=5000, debug=False)
