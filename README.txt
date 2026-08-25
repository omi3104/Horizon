============================================================
  Document Compression Agent
  Advanced local PDF compression with web interface
============================================================

QUICK START
-----------
1. Run install.bat   (first time only — installs Python packages)
2. Run start.bat     (every time you want to use the agent)
3. Browser opens at  http://localhost:5000
4. Drop your PDFs → choose a preset → click Compress All

COMPRESSION PRESETS
-------------------
  Light       Max quality · roughly 20-45% size reduction
  Balanced    Great quality · roughly 50-75% size reduction  ← default
  Aggressive  High compression · roughly 70-90% reduction
  Maximum     Smallest file · up to 99% reduction on heavy scans

ENGINES (best results with Ghostscript installed)
-------------------------------------------------
  Ghostscript — best overall (handles fonts, complex PDFs, images)
    Download: https://www.ghostscript.com/releases/gsdnld.html
    Install the 64-bit version for Windows.

  PyMuPDF + pikepdf — fallback (great for image-heavy PDFs)
    Installed automatically by install.bat

HOW MUCH CAN IT COMPRESS?
--------------------------
  • Scanned documents (no real text): up to 95-99%
  • Office docs exported to PDF: typically 40-75%
  • PDFs with mostly text: typically 20-40%
  • Already-optimized PDFs: minimal (5-15%)

  Results vary by content. The agent never makes a file larger —
  if compression would increase size, the original is returned.

PRIVACY
-------
  All processing happens locally on your PC.
  No files are uploaded to the internet. Ever.

FILES & FOLDERS
---------------
  app.py               — server (do not move)
  compression_engine.py — compression logic
  templates/index.html  — web interface
  uploads/              — temporary upload storage (auto-cleaned)
  compressed/           — output files (cleared when you click Clear)

TROUBLESHOOTING
---------------
  Q: Browser doesn't open automatically
  A: Open Chrome/Firefox and go to http://localhost:5000

  Q: "Flask not installed" error
  A: Run install.bat as Administrator

  Q: Compression is slow
  A: Large files take time. 100MB PDF may take 30-60 seconds.
     Ghostscript is faster than the PyMuPDF fallback.

  Q: Output file is same size as input
  A: The PDF is already well-optimised. Try Maximum preset.

============================================================
