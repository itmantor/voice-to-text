"""
Voice-to-Text — تبدیل فایل صوتی به متن با API پلتفرم OpenAI

- ورود با رمز عبور (از متغیر محیطی APP_PASSWORD)
- کلید API بعد از ورود، از صفحهٔ تنظیمات وارد و روی سرور ذخیره می‌شود (نه در گیت)
- فایل صوتی با ffmpeg به تکه‌های کوتاه تقسیم و تکه‌به‌تکه به OpenAI فرستاده می‌شود
- پردازش در پس‌زمینه انجام می‌شود تا فایل‌های طولانی هم قطع نشوند
"""

import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

# ---------------------------------------------------------------- تنظیمات

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
UPLOAD_DIR = DATA_DIR / "uploads"
SETTINGS_FILE = DATA_DIR / "settings.json"

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
CHUNK_SECONDS = int(os.environ.get("CHUNK_SECONDS", "600"))  # تکه‌های ۱۰ دقیقه‌ای

MODELS = {
    "gpt-transcribe": "gpt-transcribe (پیشنهادی، جدیدترین)",
    "gpt-4o-transcribe": "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe": "gpt-4o-mini-transcribe (ارزان‌تر)",
    "whisper-1": "whisper-1 (قدیمی)",
}
DEFAULT_MODEL = "gpt-transcribe"

MAX_LOGIN_FAILS = 5
LOCK_SECONDS = 10 * 60

if not APP_PASSWORD or not SECRET_KEY:
    raise SystemExit("APP_PASSWORD و SECRET_KEY باید در فایل .env تنظیم شوند.")

for d in (JOBS_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
jobs_lock = threading.Lock()
work_queue: "queue.Queue[str]" = queue.Queue()
login_fails: dict = {}  # ip -> [count, first_fail_time]

# ---------------------------------------------------------------- ذخیره‌سازی


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_settings(data: dict) -> None:
    _write_json(SETTINGS_FILE, data)


def job_path(job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(404)
    return JOBS_DIR / f"{job_id}.json"


def load_job(job_id: str) -> dict:
    p = job_path(job_id)
    if not p.exists():
        raise HTTPException(404)
    return json.loads(p.read_text(encoding="utf-8"))


def update_job(job_id: str, **fields) -> dict:
    with jobs_lock:
        job = load_job(job_id)
        job.update(fields)
        _write_json(job_path(job_id), job)
        return job


def list_jobs() -> list:
    out = []
    for p in JOBS_DIR.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            j.pop("text", None)
            out.append(j)
        except Exception:
            pass
    out.sort(key=lambda j: j.get("created", 0), reverse=True)
    return out


# ---------------------------------------------------------------- پردازش صدا


class TranscribeError(Exception):
    pass


def split_audio(src: Path, out_dir: Path) -> list:
    """فایل را به mp3 تک‌کاناله ۱۶ کیلوهرتز تبدیل و به تکه‌های CHUNK_SECONDS ثانیه‌ای تقسیم می‌کند."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
        "-f", "segment", "-segment_time", str(CHUNK_SECONDS), "-reset_timestamps", "1",
        str(out_dir / "part_%03d.mp3"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    parts = sorted(out_dir.glob("part_*.mp3"))
    if r.returncode != 0 or not parts:
        raise TranscribeError("فایل صوتی قابل خواندن نیست یا فرمت آن پشتیبانی نمی‌شود.")
    return parts


def clean_hint(s: str) -> str:
    # API درخواست‌هایی را که در prompt کاراکتر < یا > یا خط جدید دارند رد می‌کند
    s = re.sub(r"[<>\r\n]+", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()[:800]


def transcribe_part(path: Path, api_key: str, model: str, prompt: str, keywords: list) -> str:
    data: dict = {"model": model}
    if model == "gpt-transcribe":
        data["languages[]"] = ["fa"]
        if keywords:
            data["keywords[]"] = list(keywords)
    else:
        data["language"] = "fa"
    if prompt:
        data["prompt"] = prompt

    last_err = ""
    for attempt in range(4):
        try:
            with path.open("rb") as f:
                r = httpx.post(
                    f"{OPENAI_BASE_URL}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={"file": (path.name, f, "audio/mpeg")},
                    timeout=httpx.Timeout(600, connect=30),
                )
        except httpx.HTTPError as e:
            last_err = f"خطای ارتباط با OpenAI: {type(e).__name__}"
            time.sleep(3 * (attempt + 1))
            continue

        if r.status_code == 200:
            try:
                return (r.json().get("text") or "").strip()
            except ValueError:
                return r.text.strip()

        try:
            err = r.json().get("error", {}) or {}
        except ValueError:
            err = {}
        code, msg = err.get("code") or "", err.get("message") or r.text[:300]

        if r.status_code == 401:
            raise TranscribeError("کلید API نامعتبر است. از صفحهٔ تنظیمات کلید درست را وارد کنید.")
        if code == "unsupported_country_region_territory" or "country" in msg.lower():
            raise TranscribeError("OpenAI از کشور/منطقهٔ این سرور سرویس نمی‌دهد. سرور باید در منطقهٔ پشتیبانی‌شده (مثلاً آمریکا یا اروپا) باشد.")
        if code == "insufficient_quota":
            raise TranscribeError("اعتبار حساب OpenAI تمام شده است (insufficient_quota). حساب را شارژ کنید.")
        if r.status_code in (429, 500, 502, 503, 504):
            last_err = f"OpenAI موقتاً پاسخ نداد ({r.status_code}): {msg}"
            time.sleep(5 * (attempt + 1))
            continue
        raise TranscribeError(f"خطای OpenAI ({r.status_code}): {msg}")
    raise TranscribeError(last_err or "تبدیل ناموفق بود.")


def process_job(job_id: str) -> None:
    job = load_job(job_id)
    src = UPLOAD_DIR / job["stored_name"]
    work = UPLOAD_DIR / f"{job_id}_parts"
    try:
        api_key = load_settings().get("api_key", "")
        if not api_key:
            raise TranscribeError("کلید API وارد نشده است. ابتدا از صفحهٔ تنظیمات کلید را وارد کنید.")
        update_job(job_id, status="processing", step="در حال آماده‌سازی فایل...")
        parts = split_audio(src, work)
        texts = []
        for i, part in enumerate(parts, 1):
            update_job(job_id, step=f"در حال تبدیل بخش {i} از {len(parts)}...", progress=[i - 1, len(parts)])
            texts.append(transcribe_part(part, api_key, job["model"], job.get("prompt", ""), job.get("keywords", [])))
        update_job(job_id, status="done", step="انجام شد", progress=[len(parts), len(parts)],
                   text="\n\n".join(t for t in texts if t), finished=time.time())
    except TranscribeError as e:
        update_job(job_id, status="error", step=str(e))
    except Exception as e:  # خطای پیش‌بینی‌نشده
        update_job(job_id, status="error", step=f"خطای داخلی: {type(e).__name__}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            src.unlink()
        except FileNotFoundError:
            pass


def worker() -> None:
    while True:
        job_id = work_queue.get()
        try:
            process_job(job_id)
        finally:
            work_queue.task_done()


def recover_jobs() -> None:
    """کارهای نیمه‌تمام بعد از ری‌استارت دوباره در صف قرار می‌گیرند."""
    for j in sorted(list_jobs(), key=lambda j: j.get("created", 0)):
        if j.get("status") in ("queued", "processing"):
            if (UPLOAD_DIR / j["stored_name"]).exists():
                update_job(j["id"], status="queued", step="در صف انتظار...")
                work_queue.put(j["id"])
            else:
                update_job(j["id"], status="error", step="فایل اصلی پیدا نشد (سرویس ری‌استارت شده).")


# ---------------------------------------------------------------- وب‌اپ

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="v2t_session",
                   max_age=7 * 24 * 3600, same_site="strict", https_only=False)


@app.on_event("startup")
def _startup() -> None:
    recover_jobs()
    threading.Thread(target=worker, daemon=True).start()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # جلوگیری از درخواست‌های جعلی از سایت‌های دیگر (CSRF)
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if origin.split("://", 1)[-1] != host:
                return PlainTextResponse("Forbidden", status_code=403)
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # same-origin (نه no-referrer): با no-referrer مرورگر Origin را null می‌فرستد و ورود رد می‌شود
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    )
    return resp


def logged_in(request: Request) -> bool:
    return request.session.get("auth") is True


def require_login(request: Request) -> None:
    if not logged_in(request):
        raise HTTPException(401, "ابتدا وارد شوید.")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def page(name: str) -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "static" / name).read_text(encoding="utf-8"))


@app.get("/static/{name}")
def static(name: str):
    if name not in ("style.css", "app.js"):
        raise HTTPException(404)
    return FileResponse(BASE_DIR / "static" / name)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return page("index.html")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if logged_in(request):
        return RedirectResponse("/", status_code=303)
    return page("login.html")


@app.post("/login")
def login(request: Request, password: str = Form(...)):
    ip = client_ip(request)
    now = time.time()
    count, first = login_fails.get(ip, [0, now])
    if now - first > LOCK_SECONDS:
        count, first = 0, now
    if count >= MAX_LOGIN_FAILS:
        return RedirectResponse("/login?e=locked", status_code=303)
    if secrets.compare_digest(password.encode(), APP_PASSWORD.encode()):
        login_fails.pop(ip, None)
        request.session.clear()
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)
    login_fails[ip] = [count + 1, first]
    time.sleep(1)
    return RedirectResponse("/login?e=bad", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/api/settings")
def get_settings(request: Request):
    require_login(request)
    key = load_settings().get("api_key", "")
    masked = (key[:7] + "..." + key[-4:]) if len(key) > 12 else ("تنظیم شده" if key else "")
    return {"has_key": bool(key), "masked": masked, "models": MODELS, "default_model": DEFAULT_MODEL}


@app.post("/api/settings")
def set_settings(request: Request, api_key: str = Form(...)):
    require_login(request)
    api_key = api_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,300}", api_key):
        raise HTTPException(400, "فرمت کلید درست نیست. کلید معمولاً با sk- شروع می‌شود.")
    s = load_settings()
    s["api_key"] = api_key
    save_settings(s)
    return {"ok": True}


@app.post("/api/settings/test")
def test_key(request: Request):
    require_login(request)
    key = load_settings().get("api_key", "")
    if not key:
        raise HTTPException(400, "کلیدی ذخیره نشده است.")
    try:
        r = httpx.get(f"{OPENAI_BASE_URL}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ارتباط با OpenAI برقرار نشد ({type(e).__name__}).")
    if r.status_code == 200:
        return {"ok": True, "message": "کلید معتبر است و سرور به OpenAI دسترسی دارد."}
    try:
        msg = r.json().get("error", {}).get("message", "")
    except ValueError:
        msg = r.text[:200]
    raise HTTPException(400, f"کلید پذیرفته نشد ({r.status_code}): {msg}")


@app.post("/api/jobs")
async def create_job(request: Request, file: UploadFile = File(...), model: str = Form(DEFAULT_MODEL),
                     prompt: str = Form(""), keywords: str = Form("")):
    require_login(request)
    if model not in MODELS:
        raise HTTPException(400, "مدل نامعتبر است.")
    job_id = uuid.uuid4().hex
    orig = Path(file.filename or "audio").name[:150]
    ext = Path(orig).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext or ""):
        ext = ".bin"
    stored = f"{job_id}{ext}"
    dest = UPLOAD_DIR / stored
    limit = MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"حجم فایل بیشتر از {MAX_UPLOAD_MB} مگابایت است.")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "فایل خالی است.")

    kw = [clean_hint(k)[:100] for k in re.split(r"[,،\n]", keywords or "") if clean_hint(k)][:50]
    job = {
        "id": job_id, "filename": orig, "stored_name": stored, "size": size, "model": model,
        "prompt": clean_hint(prompt), "keywords": kw, "status": "queued", "step": "در صف انتظار...",
        "progress": [0, 0], "created": time.time(),
    }
    with jobs_lock:
        _write_json(job_path(job_id), job)
    work_queue.put(job_id)
    return {"id": job_id}


@app.get("/api/jobs")
def jobs(request: Request):
    require_login(request)
    return list_jobs()


@app.get("/api/jobs/{job_id}")
def job(request: Request, job_id: str):
    require_login(request)
    j = load_job(job_id)
    j.pop("stored_name", None)
    return j


@app.get("/api/jobs/{job_id}/download")
def download(request: Request, job_id: str):
    require_login(request)
    j = load_job(job_id)
    if j.get("status") != "done":
        raise HTTPException(400, "متن هنوز آماده نیست.")
    name = Path(j["filename"]).stem + ".txt"
    from urllib.parse import quote
    return PlainTextResponse(
        j.get("text", ""), media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@app.delete("/api/jobs/{job_id}")
def delete_job(request: Request, job_id: str):
    require_login(request)
    j = load_job(job_id)
    if j.get("status") in ("queued", "processing"):
        raise HTTPException(400, "این کار در حال پردازش است و فعلاً قابل حذف نیست.")
    job_path(job_id).unlink(missing_ok=True)
    return {"ok": True}


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 401 and not request.url.path.startswith("/api/"):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
