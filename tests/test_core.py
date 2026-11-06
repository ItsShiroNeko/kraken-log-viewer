import os

import pytest

from kraken_viewer import cli
from kraken_viewer.analyses import TABS
from kraken_viewer.loader import cmd_segments, get_window, load_log
from kraken_viewer.report import build_html, run_all
from kraken_viewer.utils import wrap180


def test_wrap180():
    assert wrap180(190) == pytest.approx(-170)
    assert wrap180(-190) == pytest.approx(170)


def test_load_log(sample_csv):
    d = load_log(sample_csv)
    assert d.timebase.startswith("t_mcu")
    assert d.df["t"].iloc[0] == 0
    assert d.duration == pytest.approx(119.95, abs=0.1)
    assert len(cmd_segments(d.df)) == 3


def test_load_log_rejects_foreign_csv(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n3,4\n5,6\n")
    with pytest.raises(ValueError):
        load_log(str(p))


def test_window(sample_csv):
    d = load_log(sample_csv)
    w = get_window(d, {"t0": "10", "t1": "20"})
    assert w["t"].min() >= 10 and w["t"].max() <= 20


def test_all_analyses_run(sample_csv):
    d = load_log(sample_csv)
    results = run_all(d, {})
    assert [r[0] for r in results] == [t[0] for t in TABS]
    for name, fig, text in results:
        assert "Gagal menganalisis" not in text, (name, text)
        assert fig is not None or text


def test_html_report(sample_csv):
    d = load_log(sample_csv)
    html = build_html(d, {}, run_all(d, {}))
    assert "<h1>Laporan Analisis Log Kraken</h1>" in html and "data:image/png;base64" in html


def test_cli_report(sample_csv, tmp_path):
    out = tmp_path / "laporan.html"
    assert cli.main([sample_csv, "--report", str(out), "--set", "t0=5", "--set", "t1=100"]) == 0
    assert os.path.getsize(out) > 10000
