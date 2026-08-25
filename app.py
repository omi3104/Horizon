"""
Horizon — Document Compression & PDF Tools Agent
Flask backend
"""
import os, uuid, threading, zipfile, shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file

BASE    = Path(__file__).parent
UPLOADS = BASE / "uploads"
OUTPUT  = BASE / "compressed"
UPLOADS.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = None   # unlimited uploads

jobs: dict  = {}
jobs_lock   = threading.Lock()

from compression_engine import CompressionEngine
from tools_engine import ToolsEngine

engine       = CompressionEngine()
tools_engine = ToolsEngine()


# ── helpers ───────────────────────────────────────────────────────────────────
def human_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def safe_name(s: str) -> str:
    return s.replace("..", "").replace("/", "_").replace("\\", "_")

def parse_ranges(s: str):
    """'1-3,5-7' → [(1,3),(5,7)]"""
    result = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try: result.append((int(a), int(b)))
            except: pass
    return result

def _run_tool_job(jid, fn, opath, oname):
    """Generic async runner for any tool job."""
    def task():
        try:
            with jobs_lock:
                jobs[jid].update({"status": "running", "progress": 5})
            def cb(p):
                with jobs_lock: jobs[jid]["progress"] = p
            fn(cb)
            outsz = os.path.getsize(opath) if os.path.exists(opath) else 0
            if outsz == 0:
                raise RuntimeError("Tool produced an empty output file.")
            with jobs_lock:
                jobs[jid].update({
                    "status": "done", "progress": 100,
                    "output_path": opath, "output_name": oname,
                    "output_size": outsz,
                    "output_size_h": human_size(outsz),
                })
        except Exception as e:
            with jobs_lock:
                jobs[jid].update({"status": "error", "progress": 0, "error": str(e)})
    threading.Thread(target=task, daemon=True).start()


# ── core routes ───────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/system")
def system_check():
    c  = engine.capabilities()
    tc = tools_engine.capabilities()
    if c["ghostscript"]:
        es, lv = f"Ghostscript  ·  {c['ghostscript_path']}", "excellent"
    elif c["pymupdf"]:
        es, lv = "PyMuPDF + pikepdf", "good"
    else:
        es, lv = "No engine found — run install.bat", "none"
    c["engine_str"] = es
    c["level"]      = lv
    c["tools"]      = tc
    return jsonify(c)

@app.route("/api/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files"}), 400
    out = []
    for f in files:
        if not f.filename: continue
        fid  = str(uuid.uuid4())
        name = safe_name(f.filename)
        path = UPLOADS / f"{fid}_{name}"
        f.save(str(path))
        sz   = os.path.getsize(path)
        out.append({"id": fid, "name": f.filename, "path": str(path),
                    "size": sz, "size_human": human_size(sz)})
    return jsonify({"files": out})

# ── compress ──────────────────────────────────────────────────────────────────
@app.route("/api/compress", methods=["POST"])
def compress():
    d     = request.json
    fid   = d["file_id"]; fname = d["file_name"]
    fpath = d["file_path"]; preset = d.get("preset","balanced")
    jid   = str(uuid.uuid4())
    with jobs_lock:
        jobs[jid] = {"status":"queued","progress":0,"file_name":fname}
    def run():
        try:
            with jobs_lock: jobs[jid].update({"status":"compressing","progress":5})
            oname = fname
            opath = str(OUTPUT / f"{jid}_{oname}")
            insz  = os.path.getsize(fpath)
            def cb(p):
                with jobs_lock: jobs[jid]["progress"] = p
            engine.compress(fpath, opath, preset, cb)
            outsz = os.path.getsize(opath)
            ratio = max(0.0, round((1-outsz/insz)*100, 1)) if insz else 0
            with jobs_lock:
                jobs[jid].update({
                    "status":"done","progress":100,
                    "output_path":opath,"output_name":oname,
                    "input_size":insz,"output_size":outsz,"ratio":ratio,
                    "input_size_h":human_size(insz),"output_size_h":human_size(outsz),
                    "saved_h":human_size(max(0,insz-outsz)),
                })
            try: os.remove(fpath)
            except: pass
        except Exception as e:
            with jobs_lock: jobs[jid].update({"status":"error","progress":0,"error":str(e)})
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": jid})

# ── status / download / clear ─────────────────────────────────────────────────
@app.route("/api/status/<jid>")
def status(jid):
    with jobs_lock: return jsonify(dict(jobs.get(jid, {"status":"not_found"})))

@app.route("/api/download/<jid>")
def download(jid):
    with jobs_lock: j = dict(jobs.get(jid,{}))
    if j.get("status") != "done": return "Not ready", 404
    return send_file(j["output_path"], as_attachment=True,
                     download_name=j["output_name"])

@app.route("/api/download-batch", methods=["POST"])
def download_batch():
    ids = request.json.get("job_ids", [])
    with jobs_lock:
        ready = [dict(jobs[i]) for i in ids if i in jobs and jobs[i]["status"]=="done"]
    if not ready: return "No files ready", 404
    zp = str(OUTPUT / f"batch_{uuid.uuid4()}.zip")
    with zipfile.ZipFile(zp,"w",zipfile.ZIP_DEFLATED) as zf:
        for j in ready: zf.write(j["output_path"], j["output_name"])
    return send_file(zp, as_attachment=True, download_name="horizon_compressed.zip")

@app.route("/api/clear", methods=["POST"])
def clear_all():
    ids = (request.json or {}).get("job_ids", [])
    with jobs_lock:
        for i in ids:
            j = jobs.pop(i, {})
            p = j.get("output_path")
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass
    return jsonify({"ok": True})

# ── MERGE ─────────────────────────────────────────────────────────────────────
@app.route("/api/merge", methods=["POST"])
def merge():
    d     = request.json
    paths = d["paths"]
    oname = safe_name(d.get("output_name", "merged.pdf"))
    if not oname.endswith(".pdf"): oname += ".pdf"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.merge(paths, opath, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── SPLIT ─────────────────────────────────────────────────────────────────────
@app.route("/api/split", methods=["POST"])
def split():
    d      = request.json
    path   = d["path"]
    mode   = d.get("mode", "each")
    ranges = parse_ranges(d.get("ranges", ""))
    jid    = str(uuid.uuid4())
    oname  = "split_pages.zip"
    opath  = str(OUTPUT / f"{jid}_{oname}")
    tmp_dir= str(OUTPUT / f"{jid}_split_tmp")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb):
        pages = tools_engine.split(path, tmp_dir, mode, ranges, cb)
        with zipfile.ZipFile(opath, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in pages: zf.write(p, os.path.basename(p))
        shutil.rmtree(tmp_dir, ignore_errors=True)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── PDF → IMAGES ──────────────────────────────────────────────────────────────
@app.route("/api/pdf-to-images", methods=["POST"])
def pdf_to_images():
    d      = request.json
    path   = d["path"]
    dpi    = int(d.get("dpi", 150))
    fmt    = d.get("format", "PNG")
    jid    = str(uuid.uuid4())
    oname  = "pdf_images.zip"
    opath  = str(OUTPUT / f"{jid}_{oname}")
    tmp_dir= str(OUTPUT / f"{jid}_imgs_tmp")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb):
        imgs = tools_engine.pdf_to_images(path, tmp_dir, dpi, fmt, cb)
        with zipfile.ZipFile(opath, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in imgs: zf.write(p, os.path.basename(p))
        shutil.rmtree(tmp_dir, ignore_errors=True)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── IMAGES → PDF ──────────────────────────────────────────────────────────────
@app.route("/api/images-to-pdf", methods=["POST"])
def images_to_pdf():
    d     = request.json
    paths = d["paths"]
    oname = safe_name(d.get("output_name", "images.pdf"))
    if not oname.endswith(".pdf"): oname += ".pdf"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.images_to_pdf(paths, opath, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── PDF → WORD ────────────────────────────────────────────────────────────────
@app.route("/api/pdf-to-word", methods=["POST"])
def pdf_to_word():
    d     = request.json
    path  = d["path"]
    ocr   = bool(d.get("ocr", False))
    fname = d.get("file_name", "document.pdf")
    oname = Path(fname).stem + ".docx"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.pdf_to_word(path, opath, ocr, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── PROTECT ───────────────────────────────────────────────────────────────────
@app.route("/api/protect", methods=["POST"])
def protect():
    d     = request.json
    path  = d["path"]; pw = d["password"]
    fname = d.get("file_name", "document.pdf")
    oname = Path(fname).stem + "_protected.pdf"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.protect(path, opath, pw, None, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── UNLOCK ────────────────────────────────────────────────────────────────────
@app.route("/api/unlock", methods=["POST"])
def unlock():
    d     = request.json
    path  = d["path"]; pw = d.get("password", "")
    fname = d.get("file_name", "document.pdf")
    oname = Path(fname).stem + "_unlocked.pdf"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.unlock(path, opath, pw, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── FLATTEN / SCAN LOOK ───────────────────────────────────────────────────────
@app.route("/api/flatten", methods=["POST"])
def flatten():
    d     = request.json
    path  = d["path"]; style = d.get("style", "scan")
    fname = d.get("file_name", "document.pdf")
    oname = fname  # keep the original filename
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.flatten(path, opath, style, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── WATERMARK ─────────────────────────────────────────────────────────────────
@app.route("/api/watermark", methods=["POST"])
def watermark():
    d        = request.json
    path     = d["path"]; text = d.get("text", "CONFIDENTIAL")
    opacity  = float(d.get("opacity", 0.15))
    fontsize = int(d.get("fontsize", 30))
    fname    = d.get("file_name", "document.pdf")
    oname    = Path(fname).stem + "_watermarked.pdf"
    jid      = str(uuid.uuid4())
    opath    = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb):
        tools_engine.watermark(path, opath, text, opacity, (180,180,180), 45, fontsize, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── ROTATE ────────────────────────────────────────────────────────────────────
@app.route("/api/rotate", methods=["POST"])
def rotate():
    d     = request.json
    path  = d["path"]; angle = int(d.get("angle", 90))
    fname = d.get("file_name", "document.pdf")
    oname = Path(fname).stem + f"_rotated.pdf"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status":"queued","progress":0,"file_name":oname}
    def fn(cb): tools_engine.rotate(path, opath, angle, "all", cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})


# ── EDIT PDF ──────────────────────────────────────────────────────────────────
@app.route("/api/edit-analyze", methods=["POST"])
def edit_analyze():
    d    = request.json
    path = d["path"]
    try:
        data = tools_engine.edit_analyze(path)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/edit-render", methods=["GET"])
def edit_render():
    """Return page as base64 data URL + pixel dimensions in JSON.
    Using JSON+base64 avoids every WebView2 restriction on binary responses,
    blob URLs, and canvas-drawing-while-hidden."""
    path     = request.args.get("path", "")
    page_num = int(request.args.get("page", 0))
    dpi      = int(request.args.get("dpi", 130))
    try:
        import fitz, base64
        doc  = fitz.open(path)
        if page_num >= len(doc):
            return jsonify({"error": "Page out of range"}), 400
        page = doc[page_num]
        mat  = fitz.Matrix(dpi / 72, dpi / 72)
        pix  = page.get_pixmap(matrix=mat)
        png  = pix.tobytes("png")
        b64  = base64.b64encode(png).decode("ascii")
        w, h = pix.width, pix.height
        doc.close()
        return jsonify({
            "src": f"data:image/png;base64,{b64}",
            "width": w,
            "height": h
        })
    except Exception as e:
        return Response(str(e), status=500)

@app.route("/api/edit-save", methods=["POST"])
def edit_save():
    d     = request.json
    path  = d["path"]
    edits = d.get("edits", [])
    fname = d.get("file_name", "document.pdf")
    oname = Path(fname).stem + "_edited.pdf"
    jid   = str(uuid.uuid4())
    opath = str(OUTPUT / f"{jid}_{oname}")
    with jobs_lock: jobs[jid] = {"status": "queued", "progress": 0, "file_name": oname}
    def fn(cb): tools_engine.edit_apply(path, opath, edits, cb)
    _run_tool_job(jid, fn, opath, oname)
    return jsonify({"job_id": jid})

# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import webbrowser
    print("\n━"*27)
    print("  HORIZON  ·  PDF Tools Suite  [Browser Debug Mode]")
    print("━"*27)
    print(f"  GS    : {'✓  '+str(engine.ghostscript_path) if engine.ghostscript_available else '✗'}")
    print(f"  MuPDF : {'✓' if engine.pymupdf_available else '✗'}")
    print(f"  pike  : {'✓' if engine.pikepdf_available else '✗'}")
    print(f"  docx  : {'✓' if tools_engine.docx_ok else '✗'}")
    print(f"  OCR   : {'✓' if tools_engine.tesseract_ok else '✗ (Tesseract not found)'}")
    print("\n  http://localhost:5000\n")
    if not os.environ.get("HORIZON_DESKTOP"):
        threading.Timer(1.4, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
