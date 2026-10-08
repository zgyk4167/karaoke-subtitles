#!/usr/bin/env python3
"""karaoke-subtitles: burn word-by-word karaoke subtitles, with optional Chinese
glosses, into an English-language video.

Steps. Each step reads and writes fixed file names in the job directory (--work):
  doctor                    check tools, configuration and the key's region (free)
  fetch <url-or-file>       -> src.mp4
  transcribe                -> audio.mp3, asr_task.json, transcription.json  (paid API)
  annotate                  -> annotations.json                              (paid API)
  ass                       -> subs.ass
  render                    -> karaoke.mp4
  all <url-or-file>         fetch, transcribe, annotate, ass, render

A step skips work whose output already exists, so rerunning a command resumes it.
Use --force on a single step to redo it. Progress goes to stderr; the path of
each step's output file goes to stdout.

Exit codes: 0 done, 1 unexpected failure, 2 usage error, 3 environment not ready
(missing tool, key or setting), 4 remote service failed (download, ASR, LLM),
5 input from an earlier step is missing.

Configuration comes from environment variables, then from .env in the skill
directory: DASHSCOPE_API_KEY (required), DASHSCOPE_BASE, AUDIO_URL_CMD (optional).
The ASR API reads audio from a URL. By default, transcribe uploads the job's
audio to DashScope's free temporary storage (kept 48 h), so no bucket is needed.
"""
import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONTS = os.path.join(ROOT, "assets", "fonts")
FONT_FILE = os.path.join(FONTS, "NotoSansCJKsc-Bold.otf")

DEFAULT_BASE = "https://dashscope.aliyuncs.com"
REGIONS = {"https://dashscope.aliyuncs.com": "Beijing", "https://dashscope-intl.aliyuncs.com": "Singapore"}
ASR_MODEL = "qwen-audio-3.1-asr-flash-filetrans"
ASR_FALLBACK = "fun-asr"
GLOSS_MODEL = "qwen-plus"
ASR_POLL_SECONDS = 10      # the async ASR task usually runs for minutes; 10 s keeps polling cheap
GLOSS_BATCH_LINES = 80     # subtitle lines per LLM request
GLOSS_WORKERS = 6          # parallel LLM requests
GLOSS_RETRIES = 3          # attempts per batch before it is reported as failed

SRC, AUDIO, TASK, TRANSCRIPT = "src.mp4", "audio.mp3", "asr_task.json", "transcription.json"
ANNOTATIONS, SUBS, OUTPUT = "annotations.json", "subs.ass", "karaoke.mp4"

OK, FAIL, USAGE, ENV, REMOTE, MISSING_INPUT = 0, 1, 2, 3, 4, 5


class StepError(Exception):
    """A failure with an exit code and a next action for the caller."""

    def __init__(self, code, msg, next_action=None):
        super().__init__(msg)
        self.code, self.msg, self.next_action = code, msg, next_action


def log(*parts):
    print(*parts, file=sys.stderr, flush=True)


def load_env():
    """Read KEY=VALUE lines from <skill>/.env. Variables already set in the environment win."""
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and v:
                os.environ.setdefault(k, v)


load_env()


def base_url():
    return os.environ.get("DASHSCOPE_BASE", DEFAULT_BASE).rstrip("/")


def api_key():
    k = os.environ.get("DASHSCOPE_API_KEY")
    if not k:
        raise StepError(ENV, "DASHSCOPE_API_KEY is not set.",
                        "Export DASHSCOPE_API_KEY, or copy .env.example to .env in the skill directory and set it there.")
    return k


def need(tool):
    if shutil.which(tool) is None:
        raise StepError(ENV, f"{tool} was not found on PATH.",
                        "Run scripts/install.sh, then `pipeline.py doctor`.")


def run(cmd, **kw):
    need(cmd[0])
    log("+ " + shlex.join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def job_path(work, name):
    return os.path.join(work, name)


def exists(p):
    return os.path.isfile(p) and os.path.getsize(p) > 0


def require(work, name, producer):
    p = job_path(work, name)
    if not exists(p):
        raise StepError(MISSING_INPUT, f"{p} does not exist.",
                        f"Run `pipeline.py {producer} --work {shlex.quote(work)}` first.")
    return p


def skip(p):
    log(f"skip: {p} exists (use --force to redo)")
    return p


def http(method, url, body=None, headers=None, timeout=120):
    h = {"Authorization": "Bearer " + api_key(), "Content-Type": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            hint = ("Check DASHSCOPE_API_KEY, and check that DASHSCOPE_BASE matches the key's region "
                    "(references/prerequisites.md).")
        elif e.code in (400, 404):
            hint = "Check that the model is available and enabled for your key's region (references/dashscope-api.md)."
        else:
            hint = "Wait and rerun the same command; finished work is kept."
        raise StepError(REMOTE, f"DashScope returned HTTP {e.code}: {detail}", hint)
    except (urllib.error.URLError, OSError) as e:
        raise StepError(REMOTE, f"Cannot reach {base_url()}: {e}",
                        "Check network access to DASHSCOPE_BASE, then rerun the same command.")


# ---------------- doctor ----------------
def cmd_doctor(a):
    rows, failed = [], False

    def row(status, name, detail):
        nonlocal failed
        failed = failed or status == "FAIL"
        rows.append(f"{status:<5} {name:<18} {detail}")

    v = sys.version_info
    row("ok" if v >= (3, 9) else "FAIL", "python", f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 9) else "; need 3.9+"))
    if shutil.which("ffmpeg"):
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        missing = [n for n, ok in (("libass", " ass " in filters), ("libx264", "libx264" in encoders)) if not ok]
        row("FAIL" if missing else "ok", "ffmpeg",
            "missing " + " and ".join(missing) + "; install an ffmpeg build with them" if missing else "libass and libx264 present")
    else:
        row("FAIL", "ffmpeg", "not found; run scripts/install.sh")
    row("ok" if shutil.which("ffprobe") else "FAIL", "ffprobe", "found" if shutil.which("ffprobe") else "not found; it ships with ffmpeg")
    row("ok" if shutil.which("yt-dlp") else "warn", "yt-dlp",
        "found" if shutil.which("yt-dlp") else "not found; needed only for URL input; run scripts/install.sh")
    row("ok" if exists(FONT_FILE) else "FAIL", "font",
        "assets/fonts/NotoSansCJKsc-Bold.otf" if exists(FONT_FILE) else "missing; run scripts/install.sh")
    row("ok" if os.environ.get("DASHSCOPE_API_KEY") else "FAIL", "DASHSCOPE_API_KEY",
        "set (value not shown)" if os.environ.get("DASHSCOPE_API_KEY") else "not set; see .env.example")
    row("ok", "DASHSCOPE_BASE", base_url() + (f" ({REGIONS[base_url()]})" if base_url() in REGIONS else ""))
    row("ok", "audio URL", "AUDIO_URL_CMD (your storage)" if os.environ.get("AUDIO_URL_CMD")
        else "DashScope temporary storage (default; no bucket needed)")
    if os.environ.get("DASHSCOPE_API_KEY") and not a.offline:
        row(*region_check())
    print("\n".join(rows))
    if failed:
        raise StepError(ENV, "Environment not ready.", "Fix each FAIL row above, then rerun `pipeline.py doctor`.")
    return None


def key_accepted(base):
    """One free request (an upload policy; nothing is uploaded). Returns True, False, or an error string."""
    req = urllib.request.Request(base + "/api/v1/uploads?action=getPolicy&model=" + urllib.parse.quote(ASR_MODEL),
                                 headers={"Authorization": "Bearer " + os.environ["DASHSCOPE_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return False if e.code in (401, 403) else f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return f"network error: {getattr(e, 'reason', e)}"


def region_check():
    base = base_url()
    res = key_accepted(base)
    if res is True:
        return "ok", "key region", f"key accepted by {REGIONS.get(base, base)}"
    if res is not False:
        return "warn", "key region", f"not checked ({res}); use `doctor --offline` to skip this check"
    for other, name in REGIONS.items():
        if other != base and key_accepted(other) is True:
            return "FAIL", "key region", f"key belongs to {name}; set DASHSCOPE_BASE={other}"
    return "FAIL", "key region", "key rejected; check DASHSCOPE_API_KEY"


# ---------------- fetch ----------------
def has_stream(path, kind):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries", "stream=index",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def cmd_fetch(a):
    work, src = a.work, a.src
    os.makedirs(work, exist_ok=True)
    out = job_path(work, SRC)
    if exists(out) and not a.force:
        return skip(out)
    if os.path.isfile(src):
        shutil.copyfile(src, out + ".part")
        os.replace(out + ".part", out)
        return out
    if not re.match(r"https?://", src):
        raise StepError(USAGE, f"{src} is neither an existing file nor an http(s) URL.",
                        "Pass a local video file or a video page URL.")
    need("yt-dlp")
    need("ffmpeg")
    for p in glob.glob(job_path(work, "src.*")):
        os.remove(p)
    try:
        run(["yt-dlp", "--no-playlist", "-f", "bv*+ba/b", "--merge-output-format", "mp4",
             "-o", job_path(work, "src.%(ext)s"), src])
    except subprocess.CalledProcessError:
        log("yt-dlp did not finish the merge; trying to mux the downloaded streams with ffmpeg")
    if exists(out):
        return out
    parts = [p for p in glob.glob(job_path(work, "src.f*.*")) if not p.endswith(".part")]
    vids = [p for p in parts if has_stream(p, "v")]
    auds = [p for p in parts if p not in vids and has_stream(p, "a")]
    if not vids or not auds:
        raise StepError(REMOTE, "Download failed" + (": found only " + ", ".join(parts) if parts else "."),
                        "Check that the URL plays in a browser and update yt-dlp, "
                        "or download the video yourself and pass the local file.")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", vids[0], "-i", auds[0],
         "-map", "0:v", "-map", "1:a", "-c", "copy", out])
    return out


# ---------------- transcribe ----------------
def temp_upload(path, model):
    """Upload a file to DashScope's free temporary storage (kept 48 h, bound to this model and account).
    Returns an oss:// URL. Docs: https://help.aliyun.com/zh/model-studio/get-temporary-file-url"""
    r = http("GET", base_url() + "/api/v1/uploads?action=getPolicy&model=" + urllib.parse.quote(model))
    try:
        d = r["data"]
        key = d["upload_dir"] + "/" + os.path.basename(path)
        fields = [("OSSAccessKeyId", d["oss_access_key_id"]), ("Signature", d["signature"]),
                  ("policy", d["policy"]), ("x-oss-object-acl", d["x_oss_object_acl"]),
                  ("x-oss-forbid-overwrite", d["x_oss_forbid_overwrite"]), ("key", key),
                  ("success_action_status", "200")]
        host = d["upload_host"]
    except (KeyError, TypeError):
        raise StepError(REMOTE, "Unexpected upload-policy response from DashScope.",
                        "Pass --audio-url or set AUDIO_URL_CMD instead (references/prerequisites.md).")
    boundary = "----karaoke" + hashlib.sha1(os.urandom(16)).hexdigest()
    body = b""
    for k, v in fields:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    with open(path, "rb") as f:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + f.read() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(host, data=body, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise StepError(REMOTE, f"Upload to DashScope temporary storage failed: {e}",
                        "Rerun transcribe, or pass --audio-url / set AUDIO_URL_CMD instead.")
    log(f"uploaded {os.path.basename(path)} to DashScope temporary storage for {model} (expires in 48 h)")
    return "oss://" + key


def public_url(audio):
    cmd = os.environ.get("AUDIO_URL_CMD")
    if not cmd:
        return None   # caller uploads to DashScope temporary storage per model
    log("running AUDIO_URL_CMD")
    r = subprocess.run(["sh", "-c", cmd, "sh", os.path.abspath(audio)], capture_output=True, text=True)
    urls = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith(("http://", "https://", "oss://"))]
    if r.returncode != 0 or not urls:
        raise StepError(ENV, f"AUDIO_URL_CMD exited {r.returncode} without printing a URL. stderr: {r.stderr.strip()[:300]}",
                        "Run the command by hand with the audio path as $1 and fix it, or pass --audio-url.")
    return urls[0]


def submit_asr(url, model, audio=None):
    last = None
    for m in dict.fromkeys([model, ASR_FALLBACK]):
        try:
            u = url or temp_upload(audio, m)   # temporary files are bound to one model
            hdr = {"X-DashScope-Async": "enable"}
            if u.startswith("oss://"):
                hdr["X-DashScope-OssResourceResolve"] = "enable"
            r = http("POST", base_url() + "/api/v1/services/audio/asr/transcription",
                     {"model": m, "input": {"file_urls": [u]},
                      "parameters": {"channel_id": [0], "language_hints": ["en"]}},
                     hdr)
            task = {"task_id": r["output"]["task_id"], "model": m}
            log(f"submitted ASR task with model {m}")
            return task
        except KeyError:
            last = StepError(REMOTE, f"Unexpected submit response: {json.dumps(r)[:300]}",
                             "Check references/dashscope-api.md against the current API, then rerun.")
        except StepError as e:
            last = e
        log(f"model {m}: {last.msg}")
    raise last


def cmd_transcribe(a):
    work = a.work
    src = require(work, SRC, "fetch <url-or-file>")
    out, audio, task_file = job_path(work, TRANSCRIPT), job_path(work, AUDIO), job_path(work, TASK)
    if exists(out) and not a.force:
        return skip(out)
    if a.force:
        for p in (out, task_file):
            if os.path.exists(p):
                os.remove(p)
    if not exists(audio) or a.force:
        tmp = job_path(work, "audio.part.mp3")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", tmp])
        os.replace(tmp, audio)
    if exists(task_file):
        with open(task_file, encoding="utf-8") as f:
            task = json.load(f)
        log(f"resuming ASR task {task['task_id']} (delete {task_file} to submit a new one)")
    else:
        task = submit_asr(a.audio_url or public_url(audio), a.asr_model, audio)
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=1)
    status = None
    while True:
        r = http("GET", base_url() + "/api/v1/tasks/" + task["task_id"])
        st = r["output"]["task_status"]
        if st != status:
            log(f"ASR task {task['task_id']}: {st}")
            status = st
        if st in ("SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"):
            break
        time.sleep(ASR_POLL_SECONDS)
    o = r["output"]
    results = (o.get("output") or o).get("results") or o.get("results") or []
    first = results[0] if results else {}
    if st != "SUCCEEDED" or first.get("subtask_status") == "FAILED" or not first.get("transcription_url"):
        os.remove(task_file)
        detail = first.get("message") or o.get("message") or json.dumps(o)[:300]
        raise StepError(REMOTE, f"ASR task ended with status {st}: {detail}",
                        "Check that the audio URL opens without login, then rerun transcribe to submit a new task.")
    tmp = out + ".part"
    try:
        urllib.request.urlretrieve(first["transcription_url"], tmp)
    except (urllib.error.URLError, OSError) as e:
        raise StepError(REMOTE, f"Cannot download the transcription: {e}", "Rerun transcribe; it resumes the same task.")
    with open(tmp, encoding="utf-8") as f:
        if "transcripts" not in json.load(f):
            raise StepError(REMOTE, "The transcription has no 'transcripts' field.", "Rerun transcribe with --force.")
    os.replace(tmp, out)
    return out


# ---------------- words & lines ----------------
MAXW, MAXC, PAUSE = 7, 42, 1.2   # line break: max words, max characters, pause in seconds
MIN_LINE = 1.0                   # a subtitle line stays on screen at least this long when the timing allows
TAIL = 0.4                       # a line stays this long after its last word, unless the next line starts


def chars(ws):
    return sum(len(w[2]) + 1 for w in ws) - 1


def fits(ws):
    return len(ws) <= MAXW and chars(ws) <= MAXC


def span(ws):
    return ws[-1][1] - ws[0][0]


def fix_short_lines(lines, breaks):
    """Give lines shorter than MIN_LINE more words, so no line flashes by.
    breaks[i] tells why line i starts: "sentence", "pause" or "limit" (the previous line was full)."""
    i = 0
    while i < len(lines):
        ln = lines[i]
        if span(ln) >= MIN_LINE or len(lines) == 1:
            i += 1
            continue
        prev = lines[i - 1] if i > 0 else None
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        # 1. same sentence as the previous line: move words over from its end
        if prev and breaks[i] == "limit":
            moved = False
            while len(prev) > 2 and span(ln) < MIN_LINE and fits([prev[-1]] + ln) and span(prev[:-1]) >= MIN_LINE:
                ln.insert(0, prev.pop())
                moved = True
            if span(ln) >= MIN_LINE:
                i += 1
                continue
            if moved:
                continue
        # 2. join the next or the previous line when the gap is short and the result fits
        if nxt and nxt[0][0] - ln[-1][1] <= PAUSE and fits(ln + nxt):
            lines[i] = ln + nxt
            del lines[i + 1], breaks[i + 1]
            continue
        if prev and ln[0][0] - prev[-1][1] <= PAUSE and fits(prev + ln):
            lines[i - 1] = prev + ln
            del lines[i], breaks[i]
            continue
        i += 1   # no fit: build_ass keeps it on screen longer instead
    return lines


def load_lines(work):
    with open(require(work, TRANSCRIPT, "transcribe"), encoding="utf-8") as f:
        data = json.load(f)
    words = []
    for t in data["transcripts"]:
        for s in t["sentences"]:
            sw = s.get("words") or []
            first = True
            for w in sw:
                raw = w.get("text", "") + w.get("punctuation", "")
                if not raw.strip():
                    continue
                b, e = w["begin_time"] / 1000.0, w["end_time"] / 1000.0
                if not first and not raw[0].isspace() and words and words[-1] is not None:
                    pb, _, pt = words[-1]
                    words[-1] = (pb, e, pt + raw.strip())  # merge sub-word piece
                else:
                    words.append((b, e, raw.strip()))
                first = False
            if sw:
                words.append(None)
    lines, breaks, cur, why = [], [], [], "sentence"
    for w in words:
        if w is None:
            if cur:
                lines.append(cur)
                breaks.append(why)
                cur, why = [], "sentence"
            continue
        if cur and (len(cur) >= MAXW or sum(len(x[2]) + 1 for x in cur) + len(w[2]) > MAXC or w[0] - cur[-1][1] > PAUSE):
            lines.append(cur)
            breaks.append(why)
            cur, why = [], ("pause" if w[0] - cur[-1][1] > PAUSE else "limit")
        cur.append(w)
    if cur:
        lines.append(cur)
        breaks.append(why)
    return fix_short_lines(lines, breaks)


# ---------------- annotate ----------------
ANNOTATE_PROMPT = """You annotate English video subtitles for Chinese learners of English. Below are subtitles from an English video; each line starts with its number.
Find everything that a Chinese learner at the CET-6 level (China's College English Test Band 6, score around 500) would need explained, including: 1) technical terms (AI, programming, software engineering, etc., e.g. codebase, refactor, latency, regression); 2) difficult words beyond the CET-6 (500) vocabulary; 3) collocations, phrasal verbs and set phrases (e.g. figure out, end up, in terms of, take a step back, at scale); 4) idioms and idiomatic spoken expressions.
Do not mark common words a CET-6 (500) learner already knows. Do not mark spoken fillers (uh, like, you know).
For each item, give only the meaning of that word or phrase in context, as a short Simplified Chinese gloss (2-8 Chinese characters). Never translate the whole sentence.
"term" must be consecutive words that appear exactly as written in that line (no punctuation); it can be one word or a phrase. At most 3 items per line. Do not miss collocations and phrases; aim for about 1 item every 2-3 lines.
Output only a JSON array, for example: [{"id": 12, "term": "greenfield", "zh": "<Simplified Chinese gloss meaning 'brand-new project'>"}]

Subtitles:
"""


def parse_gloss_reply(content):
    """Extract the JSON array from an LLM reply; return [] when there is none."""
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        return []
    items = json.loads(m.group(0))
    return [x for x in items if isinstance(x, dict)]


def cmd_annotate(a):
    work = a.work
    out = job_path(work, ANNOTATIONS)
    lines = load_lines(work)
    if exists(out) and not a.force:
        return skip(out)
    api_key()

    def call(ids):
        text = "\n".join(f"{i}: " + " ".join(w[2] for w in lines[i]) for i in ids)
        err = None
        for _ in range(GLOSS_RETRIES):
            try:
                r = http("POST", base_url() + "/compatible-mode/v1/chat/completions",
                         {"model": a.gloss_model, "temperature": 0.2,
                          "messages": [{"role": "user", "content": ANNOTATE_PROMPT + text}]}, timeout=180)
                return parse_gloss_reply(r["choices"][0]["message"]["content"])
            except (StepError, KeyError, ValueError) as e:
                err = e
        log(f"batch starting at line {ids[0]} failed: {getattr(err, 'msg', err)}")
        return None

    batches = [list(range(i, min(i + GLOSS_BATCH_LINES, len(lines)))) for i in range(0, len(lines), GLOSS_BATCH_LINES)]
    anns, failed = [], []
    with cf.ThreadPoolExecutor(GLOSS_WORKERS) as ex:
        for ids, res in zip(batches, ex.map(call, batches)):
            if res is None:
                failed.append(ids)
            else:
                anns.extend(res)
    if batches and len(failed) == len(batches):
        raise StepError(REMOTE, "Every gloss request failed.",
                        "Check the errors above; run `pipeline.py doctor`, then rerun annotate.")
    tmp = out + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(anns, f, ensure_ascii=False, indent=0)
    os.replace(tmp, out)
    log(f"{len(lines)} lines, {len(anns)} glosses")
    if failed:
        spans = ", ".join(f"{b[0]}-{b[-1]}" for b in failed)
        log(f"warning: {len(failed)} of {len(batches)} batches failed; lines {spans} have no glosses. "
            "Rerun `annotate --force` to retry (this repeats every paid request).")
    return out


# ---------------- ASS ----------------
GREEN, WHITE, BLUE = "&H0000FF00&", "&H00FFFFFF&", "&HFFA030&"
POP_SCALE, POP_IN, POP_OUT = 122, 90, 120

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,64,&H0000FF00,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def norm(s):
    return re.sub(r"[^\w'-]", "", s.lower())


def find_term(lines, i, tt):
    """Where to put the gloss for term tokens tt reported on line i: (line, word) of the term's last word.
    Looks in line i first, then across the break into the next or previous line (the gloss goes
    after the last word, on whichever line holds it), then in the neighbouring lines alone."""
    def search(ids):
        flat = [(k, j) for k in ids for j in range(len(lines[k]))]
        toks = [norm(lines[k][j][2]) for k, j in flat]
        for s in range(len(toks) - len(tt) + 1):
            if toks[s:s + len(tt)] == tt:
                return flat[s + len(tt) - 1]
        return None
    n = len(lines)
    for ids in ([i], [i, i + 1], [i - 1, i], [i + 1], [i - 1]):
        if all(0 <= k < n for k in ids):
            pos = search(ids)
            if pos:
                return pos
    return None


def cmd_ass(a):
    work = a.work
    lines = load_lines(work)
    ins = {}
    ap = job_path(work, ANNOTATIONS)
    if not a.no_annotate and not exists(ap):
        log(f"{ap} not found; building subtitles without glosses (run annotate first to add them)")
    if not a.no_annotate and exists(ap):
        with open(ap, encoding="utf-8") as f:
            anns = json.load(f)
        for item in anns:
            try:
                i = int(item["id"])
                term = item["term"].split()
                zh = item["zh"].strip()
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if i < 0 or i >= len(lines) or not term or not zh:
                continue
            pos = find_term(lines, i, [norm(x) for x in term])
            if pos and pos not in ins:
                ins[pos] = zh
    out = []
    for i, ln in enumerate(lines):
        start, end = ln[0][0], ln[-1][1]
        nxt = lines[i + 1][0][0] if i + 1 < len(lines) else end + 1
        end = min(max(end + TAIL, start + MIN_LINE), nxt) if nxt > end else end
        cursor, text = start, ""
        for j, (b, e, t) in enumerate(ln):
            gap = round((b - cursor) * 100)
            if gap > 0:
                text += f"{{\\k{gap}}}"
            t = t.replace("{", "(").replace("}", ")")
            k = max(1, round((e - b) * 100))
            if not a.no_pop:
                t1 = int((b - start) * 1000)
                t2 = max(int((e - start) * 1000), t1 + POP_IN)
                fx = (f"\\fscx100\\fscy100\\t({t1},{t1 + POP_IN},\\fscx{POP_SCALE}\\fscy{POP_SCALE})"
                      f"\\t({t2},{t2 + POP_OUT},\\fscx100\\fscy100)")
                text += f"{{\\k{k}{fx}}}{t}{{\\fscx100\\fscy100}} "
            else:
                text += f"{{\\k{k}}}{t} "
            cursor = e
            if (i, j) in ins:
                text = text.rstrip() + f"{{\\k0\\1c{BLUE}\\2c{BLUE}}}[{ins[(i, j)]}]{{\\1c{GREEN}\\2c{WHITE}}} "
        out.append(f"Dialogue: 0,{ts(start)},{ts(end)},Default,,0,0,0,,{text.strip()}")
    p = job_path(work, SUBS)
    with open(p, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n".join(out) + "\n")
    log(f"{len(out)} lines, {len(ins)} glosses inserted")
    return p


# ---------------- render ----------------
def cmd_render(a):
    work = a.work
    src = require(work, SRC, "fetch <url-or-file>")
    ass = require(work, SUBS, "ass")
    out = os.path.abspath(a.out or job_path(work, OUTPUT))
    if exists(out) and not a.force:
        return skip(out)
    if not exists(FONT_FILE):
        raise StepError(ENV, f"{FONT_FILE} is missing.", "Run scripts/install.sh to download it.")
    need("ffmpeg")
    need("ffprobe")
    try:
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", src], text=True).strip())
    except (subprocess.CalledProcessError, ValueError):
        raise StepError(MISSING_INPUT, f"ffprobe cannot read the duration of {src}.",
                        "The download may be broken; rerun `fetch --force`.")
    with open(ass, "rb") as f:
        key = hashlib.sha1(os.path.abspath(src).encode() + f.read() + str(a.segment).encode()).hexdigest()[:12]
    # Segments go to local disk: writing to a network filesystem can fail with
    # "Error writing trailer: Input/output error". Finished segments are reused on rerun.
    tmp = os.path.join(os.path.abspath(a.tmp_dir or tempfile.gettempdir()), f"karaoke-subtitles-{key}")
    if a.force and os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)
    shutil.copyfile(ass, os.path.join(tmp, SUBS))
    if not os.path.exists(os.path.join(tmp, "fonts")):
        os.symlink(FONTS, os.path.join(tmp, "fonts"))   # relative names keep the filter graph free of escaping
    n = max(1, -(-int(dur * 1000) // (a.segment * 1000)))
    parts = []
    for i in range(n):
        s = i * a.segment
        part = f"part{i}.mp4"
        parts.append(part)
        if exists(os.path.join(tmp, part)):
            log(f"segment {i + 1}/{n}: reusing finished segment")
            continue
        log(f"segment {i + 1}/{n}")
        vf = f"setpts=PTS+{s}/TB,ass={SUBS}:fontsdir=fonts,setpts=PTS-STARTPTS"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(s), "-t", str(a.segment), "-i", os.path.abspath(src),
             "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
             f"part{i}.tmp.mp4"], cwd=tmp)
        os.replace(os.path.join(tmp, f"part{i}.tmp.mp4"), os.path.join(tmp, part))
    with open(os.path.join(tmp, "list.txt"), "w") as f:
        f.write("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-i", os.path.abspath(src),
         "-map", "0:v", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart", "final.mp4"], cwd=tmp)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.move(os.path.join(tmp, "final.mp4"), out)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


# ---------------- all ----------------
def cmd_all(a):
    a.force = False
    for step in (cmd_fetch, cmd_transcribe, cmd_annotate, cmd_ass, cmd_render):
        if step is cmd_annotate and a.no_annotate:
            continue
        print(step(a), flush=True)
    return None


# ---------------- CLI ----------------
def build_parser():
    work = argparse.ArgumentParser(add_help=False)
    work.add_argument("--work", default="./job", metavar="DIR", help="job directory for all files (default: ./job)")
    force = argparse.ArgumentParser(add_help=False)
    force.add_argument("--force", action="store_true", help="redo this step even if its output exists")
    src = argparse.ArgumentParser(add_help=False)
    src.add_argument("src", metavar="URL_OR_FILE", help="local video file, or a video page URL that yt-dlp supports")
    asr = argparse.ArgumentParser(add_help=False)
    asr.add_argument("--audio-url", metavar="URL",
                     help="public URL of the job's audio.mp3; overrides AUDIO_URL_CMD and the default temporary upload")
    asr.add_argument("--asr-model", default=ASR_MODEL, metavar="NAME",
                     help=f"ASR model (default: {ASR_MODEL}; falls back to {ASR_FALLBACK} if submit fails)")
    gloss = argparse.ArgumentParser(add_help=False)
    gloss.add_argument("--gloss-model", default=GLOSS_MODEL, metavar="NAME", help=f"LLM for glosses (default: {GLOSS_MODEL})")
    style = argparse.ArgumentParser(add_help=False)
    style.add_argument("--no-pop", action="store_true", help="disable the per-word scale-up effect")
    style.add_argument("--no-annotate", action="store_true", help="plain karaoke subtitles without Chinese glosses")
    rend = argparse.ArgumentParser(add_help=False)
    rend.add_argument("--segment", type=int, default=1200, metavar="SECONDS",
                      help="render in segments of this length, then join them (default: 1200)")
    rend.add_argument("--out", metavar="FILE", help="output video (default: <work>/karaoke.mp4)")
    rend.add_argument("--tmp-dir", metavar="DIR", help="local directory for segment files (default: system temp)")

    p = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Burn word-by-word karaoke subtitles, with optional Chinese glosses, into an English video.",
        epilog="Exit codes: 0 done, 1 unexpected failure, 2 usage error, 3 environment not ready, "
               "4 remote service failed, 5 input from an earlier step missing. "
               "Each step prints its output path on stdout; rerunning a step resumes it.")
    sub = p.add_subparsers(dest="step", required=True, metavar="STEP")

    def add(name, func, parents, help_text, description):
        sp = sub.add_parser(name, parents=parents, help=help_text, description=description)
        sp.set_defaults(func=func)

    off = argparse.ArgumentParser(add_help=False)
    off.add_argument("--offline", action="store_true", help="skip the key region check (no network at all)")
    add("doctor", cmd_doctor, [off], "check tools, configuration and the key's region (free)",
        "Check Python, ffmpeg (libass, libx264), ffprobe, yt-dlp, the bundled font and DashScope settings. "
        "If a key is set, make one free request to check that DASHSCOPE_BASE matches the key's region "
        "(Beijing or Singapore); nothing is uploaded or billed. Never prints the API key. "
        "Exits 3 if a required item is missing or the region is wrong.")
    add("fetch", cmd_fetch, [src, work, force], "copy or download the video to <work>/src.mp4",
        "Copy a local video, or download a URL with yt-dlp, to <work>/src.mp4.")
    add("transcribe", cmd_transcribe, [work, asr, force], "word-timestamped ASR to <work>/transcription.json (paid)",
        "Extract 16 kHz mono audio to <work>/audio.mp3, submit it to DashScope file transcription, and save "
        "<work>/transcription.json. The API reads audio from a URL: by default the audio is uploaded to DashScope's "
        "free temporary storage (kept 48 h); AUDIO_URL_CMD or --audio-url use your own storage instead. "
        "The task id is saved in <work>/asr_task.json, so a rerun resumes polling instead of paying again.")
    add("annotate", cmd_annotate, [work, gloss, force], "pick terms and write Chinese glosses to <work>/annotations.json (paid)",
        f"Send subtitle lines to the LLM in batches of {GLOSS_BATCH_LINES} and save the chosen terms with short "
        "Simplified Chinese glosses (CET-6 level) to <work>/annotations.json.")
    add("ass", cmd_ass, [work, style], "build <work>/subs.ass from the transcript and glosses",
        "Build ASS karaoke subtitles. Always rebuilds; the result depends only on the input files and flags.")
    add("render", cmd_render, [work, rend, force], "burn <work>/subs.ass into the video",
        "Burn the subtitles into <work>/src.mp4 with ffmpeg and libass and copy the original audio. "
        "Finished segments are kept, so a rerun after an interruption continues where it stopped.")
    add("all", cmd_all, [src, work, asr, gloss, style, rend], "run fetch, transcribe, annotate, ass and render",
        "Run every step in order. Existing outputs are reused; to redo one step, run that step with --force.")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        out = a.func(a)
        if out:
            print(out, flush=True)
        return OK
    except StepError as e:
        log(f"error: {e.msg}")
        if e.next_action:
            log(f"next: {e.next_action}")
        return e.code
    except subprocess.CalledProcessError as e:
        cmd = shlex.join(e.cmd) if isinstance(e.cmd, list) else str(e.cmd)
        log(f"error: command exited {e.returncode}: {cmd}")
        log("next: read the tool output above; run `pipeline.py doctor` if a tool looks broken.")
        return FAIL
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
