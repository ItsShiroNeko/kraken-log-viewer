"""Fungsi bantu kecil yang dipakai di seluruh paket."""
import numpy as np


def wrap180(a):
    return (np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0


def fmt(v, p=2):
    try:
        if v is None or np.isnan(v):
            return "-"
        return ("%." + str(p) + "f") % v
    except TypeError:
        return str(v)


def fnum(opts, key, default):
    try:
        s = str(opts.get(key, "")).strip()
        return float(s) if s != "" else default
    except ValueError:
        return default


def has(df, *cols):
    return all(c in df.columns and df[c].notna().sum() > 5 for c in cols)


def trapz(y, x):
    f = getattr(np, "trapezoid", None) or np.trapz
    return f(y, x)


def table(headers, rows):
    """Tabel teks rata-kiri untuk kotak teks monospace."""
    cols = list(zip(*([headers] + [[str(c) for c in r] for r in rows]))) if rows else [[h] for h in headers]
    w = [max(len(str(x)) for x in c) for c in cols]
    line = lambda r: "  ".join(str(x).ljust(wi) for x, wi in zip(r, w))
    out = [line(headers), "  ".join("-" * wi for wi in w)]
    out += [line(r) for r in rows]
    return "\n".join(out)
