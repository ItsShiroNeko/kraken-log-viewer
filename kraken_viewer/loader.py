"""Memuat log telemetri CSV dan fungsi bantu pengolahan data."""
import glob
import os

import numpy as np
import pandas as pd

from .config import DEFAULT_LOG_DIR
from .utils import fnum


class LogData(object):
    def __init__(self, df, files, timebase, name):
        self.df, self.files, self.timebase, self.name = df, files, timebase, name

    @property
    def duration(self):
        return float(self.df["t"].iloc[-1]) if len(self.df) else 0.0


def find_latest_log(root=DEFAULT_LOG_DIR):
    cands = glob.glob(os.path.join(root, "log_*", "telemetry_*.csv")) + glob.glob(os.path.join(root, "*", "telemetry_*.csv"))
    return max(cands, key=os.path.getmtime) if cands else None


def load_log(path):
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "telemetry_*.csv")))
        name = os.path.basename(os.path.normpath(path))
    else:
        files = [path]
        name = os.path.basename(os.path.dirname(os.path.abspath(path))) or os.path.basename(path)
    if not files:
        raise ValueError("Tidak ada telemetry_*.csv di folder:\n" + path)
    parts = []
    for f in files:
        d = pd.read_csv(f, comment="#", skipinitialspace=True)
        d.columns = [str(c).strip() for c in d.columns]
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    if len(df) < 3:
        raise ValueError("File terlalu pendek (%d baris)." % len(df))
    for c in df.columns:
        if c not in ("waktu", "cmd"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["cmd"] = df["cmd"].fillna("-").astype(str) if "cmd" in df.columns else "-"
    if not any(c in df.columns for c in ("roll", "pitch", "yaw", "pps_r", "pps_rxd")):
        raise ValueError("Ini bukan file log Kraken (tidak ada kolom roll/pitch/yaw/pps).")
    tb = None
    for col, label in (("t_mcu", "t_mcu (jam STM32)"), ("t_rel", "t_rel (detik sejak REC)"), ("t_host", "t_host (jam komputer)")):
        if col in df.columns and df[col].notna().sum() >= 10:
            df["t"] = df[col].astype(float)
            tb = label
            break
    if tb is None:
        df["t"] = np.arange(len(df)) * 0.05
        tb = "urutan baris x 0.05 s (tidak ada kolom waktu)"
    df = df[df["t"].notna()].sort_values("t").drop_duplicates("t").reset_index(drop=True)
    df["t"] = df["t"] - df["t"].iloc[0]
    return LogData(df, files, tb, name)


def get_window(data, opts):
    df = data.df
    m = np.ones(len(df), dtype=bool)
    t0, t1 = fnum(opts, "t0", None), fnum(opts, "t1", None)
    if t0 is not None:
        m &= df["t"].values >= t0
    if t1 is not None:
        m &= df["t"].values <= t1
    return df[m].reset_index(drop=True)


def smooth(s, n):
    n = int(n)
    return s.rolling(n, center=True, min_periods=1).mean() if n > 1 else s


def ds(w, n=15000):
    """Downsample agar grafik tetap ringan."""
    step = max(1, len(w) // n)
    return w.iloc[::step]


def cmd_segments(w):
    c, t = w["cmd"].values, w["t"].values
    if len(c) == 0:
        return []
    idx = np.r_[0, np.where(c[1:] != c[:-1])[0] + 1]
    segs = []
    for i, s in enumerate(idx):
        e = idx[i + 1] if i + 1 < len(idx) else len(c) - 1
        segs.append((c[s], float(t[s]), float(t[e])))
    return segs
