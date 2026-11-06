"""Titik masuk baris perintah.

    kraken-viewer                          buka jendela
    kraken-viewer <file.csv | folder>      langsung buka log
    kraken-viewer <log> --report out.html  laporan tanpa jendela
"""
import argparse
import sys

from . import __version__
from .config import APP_TITLE


def _parse_sets(pairs):
    opts = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit("--set harus berbentuk KUNCI=NILAI (diterima: %r)" % p)
        k, v = p.split("=", 1)
        opts[k.strip()] = v.strip()
    return opts


def build_parser():
    ap = argparse.ArgumentParser(prog="kraken-viewer", description="%s: analisis dan replay log telemetri Kraken." % APP_TITLE)
    ap.add_argument("path", nargs="?", help="file telemetry_*.csv atau folder sesi log")
    ap.add_argument("--report", metavar="OUT.html", help="buat laporan HTML tanpa membuka jendela")
    ap.add_argument("--set", action="append", metavar="KUNCI=NILAI",
                    help="opsi analisis untuk mode --report, mis. --set t0=10 --set t1=120 --set track_tol=2 (bisa diulang)")
    ap.add_argument("--version", action="version", version="%s %s" % (APP_TITLE, __version__))
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.report:
        if not args.path:
            build_parser().error("--report membutuhkan <file|folder> log")
        from .loader import load_log
        from .report import build_html, run_all
        data = load_log(args.path)
        opts = _parse_sets(args.set)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(build_html(data, opts, run_all(data, opts)))
        print("Laporan:", args.report)
        return 0

    try:
        from .gui.app import run_gui
    except ImportError as e:
        sys.exit("Tkinter belum terpasang, jadi jendela tidak bisa dibuka (%s).\n"
                 "  Ubuntu/Debian : sudo apt install python3-tk\n"
                 "  Fedora        : sudo dnf install python3-tkinter\n"
                 "  Windows       : pasang ulang Python dan centang 'tcl/tk and IDLE'\n"
                 "Tanpa GUI Anda tetap bisa membuat laporan:  kraken-viewer <log> --report laporan.html" % e)
    run_gui(args.path)
    return 0
