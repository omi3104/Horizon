"""
Compression Engine — Multi-strategy PDF compression
Strategies (in order of preference):
  1. Ghostscript  — most powerful, handles everything
  2. PyMuPDF      — re-compresses embedded images
  3. pikepdf      — stream/structural compression
"""
import os
import io
import glob
import shutil
import subprocess
import threading


# ─── Preset definitions ───────────────────────────────────────────────────────
PRESETS = {
    "light": {
        "label":       "Light  —  max quality",
        "gs_setting":  "/printer",
        "img_quality": 85,
        "target_dpi":  200,
        "max_px":      3000,
        "q_factor":    "0.15",
    },
    "balanced": {
        "label":       "Balanced  —  good quality, great savings",
        "gs_setting":  "/ebook",
        "img_quality": 72,
        "target_dpi":  120,
        "max_px":      1800,
        "q_factor":    "0.40",
    },
    "aggressive": {
        "label":       "Aggressive  —  high compression",
        "gs_setting":  "/screen",
        "img_quality": 50,
        "target_dpi":  90,
        "max_px":      1400,
        "q_factor":    "0.65",
    },
    "maximum": {
        "label":       "Maximum  —  smallest file",
        "gs_setting":  "/screen",
        "img_quality": 28,
        "target_dpi":  72,
        "max_px":      1100,
        "q_factor":    "0.85",
    },
}


class CompressionEngine:
    def __init__(self):
        self.ghostscript_path = self._find_ghostscript()
        self.ghostscript_available = self.ghostscript_path is not None
        self.pymupdf_available = self._check_lib("fitz")
        self.pikepdf_available = self._check_lib("pikepdf")

    # ── capability detection ──────────────────────────────────────────────────

    def _find_ghostscript(self):
        patterns = [
            r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
            r"C:\Program Files (x86)\gs\gs*\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs*\bin\gswin32c.exe",
            r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe",
        ]
        for pat in patterns:
            hits = sorted(glob.glob(pat))
            if hits:
                return hits[-1]
        for cmd in ("gswin64c", "gswin32c", "gs"):
            try:
                r = subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
                if r.returncode == 0:
                    return cmd
            except Exception:
                pass
        return None

    @staticmethod
    def _check_lib(name):
        try:
            __import__(name)
            return True
        except ImportError:
            return False

    def capabilities(self):
        return {
            "ghostscript":      self.ghostscript_available,
            "ghostscript_path": self.ghostscript_path,
            "pymupdf":          self.pymupdf_available,
            "pikepdf":          self.pikepdf_available,
        }

    # ── public API ────────────────────────────────────────────────────────────

    def compress(self, input_path: str, output_path: str,
                 preset: str = "balanced",
                 progress_cb=None):
        """Compress input_path → output_path using the given preset."""
        cfg = PRESETS.get(preset, PRESETS["balanced"])
        _cb = progress_cb or (lambda p: None)

        _cb(5)

        if self.ghostscript_available:
            self._gs_compress(input_path, output_path, cfg, _cb)
        elif self.pymupdf_available:
            self._mupdf_compress(input_path, output_path, cfg, _cb)
        else:
            raise RuntimeError(
                "No compression engine found.\n"
                "Please install Ghostscript (recommended) or run:\n"
                "  pip install PyMuPDF pikepdf Pillow"
            )

        # If the output somehow ended up larger, fall back to the original
        in_sz  = os.path.getsize(input_path)
        out_sz = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        if out_sz == 0:
            raise RuntimeError("Compression produced an empty file.")
        if out_sz > in_sz:
            shutil.copy2(input_path, output_path)

        _cb(100)

    # ── Ghostscript strategy ──────────────────────────────────────────────────

    def _gs_compress(self, inp, outp, cfg, cb):
        dpi = cfg["target_dpi"]
        q   = cfg["q_factor"]
        cmd = [
            self.ghostscript_path,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={cfg['gs_setting']}",
            "-dNOPAUSE", "-dQUIET", "-dBATCH",

            # ── Image downsampling ─────────────────────────────────────────
            "-dColorImageDownsampleType=/Bicubic",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dMonoImageDownsampleType=/Subsample",
            f"-dColorImageResolution={dpi}",
            f"-dGrayImageResolution={dpi}",
            "-dMonoImageResolution=300",
            "-dDownsampleColorImages=true",
            "-dDownsampleGrayImages=true",
            "-dDownsampleMonoImages=true",

            # ── FORCE recompression (key fix for already-compressed PDFs) ──
            # Default threshold is 1.5 — images only downsample if 1.5× over
            # target DPI. Setting to 1.0 means ANY image at or above target
            # gets resampled, including Foxit/Adobe optimised PDFs.
            "-dColorImageDownsampleThreshold=1.0",
            "-dGrayImageDownsampleThreshold=1.0",
            "-dMonoImageDownsampleThreshold=1.0",

            # Disable auto-filter so we can force JPEG encoding below
            "-dAutoFilterColorImages=false",
            "-dAutoFilterGrayImages=false",

            # Force JPEG (DCT) encoding for colour and grey images
            "-dColorImageFilter=/DCTEncode",
            "-dGrayImageFilter=/DCTEncode",

            # ── Structural optimisation ────────────────────────────────────
            "-dOptimize=true",
            "-dEmbedAllFonts=true",
            "-dSubsetFonts=true",
            "-dCompressFonts=true",
            "-dDetectDuplicateImages=true",
            "-dFastWebView=false",
            "-dCompressPages=true",

            f"-sOutputFile={outp}",
            inp,
        ]
        cb(20)
        # CREATE_NO_WINDOW (0x08000000) prevents Ghostscript from
        # opening any visible console window on Windows
        kwargs = {"capture_output": True, "text": True, "timeout": 600}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(cmd, **kwargs)
        cb(90)
        if result.returncode != 0:
            raise RuntimeError(f"Ghostscript error:\n{result.stderr[:800]}")

    # ── PyMuPDF strategy ──────────────────────────────────────────────────────

    def _mupdf_compress(self, inp, outp, cfg, cb):
        import fitz
        quality  = cfg["img_quality"]
        max_px   = cfg["max_px"]

        doc = fitz.open(inp)
        n   = len(doc)

        for i, page in enumerate(doc):
            cb(10 + int(70 * i / max(n, 1)))
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    base = doc.extract_image(xref)
                    raw  = base["image"]
                    self._recompress_image(page, xref, raw, quality, max_px)
                except Exception:
                    pass

        cb(85)

        # Also run pikepdf structural pass if available
        import tempfile
        if self.pikepdf_available:
            tmp = tempfile.mktemp(suffix=".pdf")
            doc.save(tmp, deflate=True, deflate_images=True,
                     deflate_fonts=True, garbage=4, clean=True)
            doc.close()
            self._pikepdf_pass(tmp, outp)
            try:
                os.remove(tmp)
            except Exception:
                pass
        else:
            doc.save(outp, deflate=True, deflate_images=True,
                     deflate_fonts=True, garbage=4, clean=True)
            doc.close()

    @staticmethod
    def _recompress_image(page, xref, raw_bytes, quality, max_px):
        from PIL import Image
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA", "CMYK"):
            img = img.convert("RGB")
        w, h = img.size
        if w > max_px or h > max_px:
            scale = min(max_px / w, max_px / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        # NOTE: doc.update_stream(xref, ...) must NOT be used here — it Flate-
        # compresses whatever bytes it's given and leaves the image XObject's
        # /Filter, /ColorSpace, /Width, /Height, /BitsPerComponent as they were
        # for the OLD (uncompressed/differently-sized) image. A reader then
        # decodes the new JPEG bytes against the old metadata, which corrupts
        # the page (colour noise + black blocks). Page.replace_image() updates
        # all of that image metadata to match the new JPEG stream correctly.
        page.replace_image(xref, stream=buf.getvalue())

    # ── pikepdf structural pass ───────────────────────────────────────────────

    def _pikepdf_pass(self, inp, outp):
        import pikepdf
        with pikepdf.open(inp) as pdf:
            pdf.save(
                outp,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                recompress_flate=True,
            )
