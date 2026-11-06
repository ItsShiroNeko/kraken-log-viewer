"""Menjalankan semua analisis dan membuat laporan HTML (tanpa GUI)."""
import base64
import datetime
import io
import traceback

from .analyses import TABS


def run_all(data, opts):
    out = []
    for name, fn, _ in TABS:
        try:
            fig, text = fn(data, opts)
        except Exception:
            fig, text = None, "Gagal menganalisis:\n" + traceback.format_exc()
        out.append((name, fig, text))
    return out


def _png_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_html(data, opts, results):
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    h = ["<!DOCTYPE html><html lang='id'><head><meta charset='utf-8'><title>Laporan %s</title>" % esc(data.name),
         "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:1150px;margin:24px auto;padding:0 12px;color:#111}"
         "h1{border-bottom:3px solid #0B3D91;padding-bottom:6px}h2{margin-top:34px;color:#0B3D91}"
         "pre{background:#f4f6fa;padding:10px;overflow-x:auto;font-size:12px;border-radius:6px}img{max-width:100%;border:1px solid #ccc}</style></head><body>",
         "<h1>Laporan Analisis Log Kraken</h1>",
         "<p>Sesi: <b>%s</b><br>Dibuat: %s<br>Basis waktu: %s</p>" % (esc(data.name), datetime.datetime.now().strftime("%d-%m-%Y %H:%M"), esc(data.timebase))]
    for name, fig, text in results:
        h.append("<h2>%s</h2>" % esc(name))
        if fig is not None:
            h.append("<img alt='%s' src='data:image/png;base64,%s'>" % (esc(name), _png_b64(fig)))
        h.append("<pre>%s</pre>" % esc(text))
    h.append("</body></html>")
    return "\n".join(h)
