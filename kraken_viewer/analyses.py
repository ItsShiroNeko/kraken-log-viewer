"""Mesin analisis log Kraken.

Setiap fungsi ``an_*`` menerima ``(data, opts)`` dan mengembalikan ``(Figure | None, teks)``.
``TABS`` adalah daftar analisis yang dipakai GUI maupun laporan HTML.
"""
import os

import numpy as np
import pandas as pd
from matplotlib import colormaps
from matplotlib.gridspec import GridSpec

from .config import CODE_MF, CODE_PPS_FWD, CODE_PPS_REV, THR, TIME_COLS
from .loader import cmd_segments, ds, get_window, smooth
from .plotting import mark_cmds, new_fig
from .utils import fmt, fnum, has, table, trapz, wrap180


def active_thrusters(w, prefix="pps_"):
    return [t for t in THR if has(w, prefix + t)]


def need(msg_cols, hint):
    return None, ("Kolom yang dibutuhkan tidak ada di log ini: %s\n\n%s" % (", ".join(msg_cols), hint))


HINT_SP = ("Aktifkan di krakenv2_logger.py (daftar LOG_COLUMNS, hapus tanda #):\n"
           '  "sp_yaw", "sp_pitch", "sp_roll", "z", "sp_z", "o_yaw", "o_pitch", "o_roll", "o_z"\n'
           '  dan setpoint dari GUI: "gui_sp_yaw", "gui_sp_pitch", "gui_sp_roll", "gui_sp_depth"')
# kolom setpoint yang diperintahkan GUI (cadangan bila setpoint dari firmware tidak berubah / palsu)
GUI_SP = {"yaw": "gui_sp_yaw", "pitch": "gui_sp_pitch", "roll": "gui_sp_roll", "z": "gui_sp_depth"}
HINT_PWM = ('Aktifkan "pwm_rxd", "pwm_lxd", "pwm_r", "pwm_l" di LOG_COLUMNS.\n'
            "Catatan: PWM hanya tersedia dengan firmware baru (DataLog.ino).")
HINT_DIST = 'Aktifkan "pul_rxd", "pul_lxd", "pul_r", "pul_l", "x", "y" di LOG_COLUMNS.'


# =====================================================================================
#  ANALISIS 1: RINGKASAN
# =====================================================================================
def an_summary(data, opts):
    w = get_window(data, opts)
    if len(w) < 3:
        return None, "Rentang waktu terlalu pendek / kosong."
    t = w["t"].values
    dt = np.diff(t)
    med = float(np.median(dt))
    L = []
    L.append("FILE      : " + "; ".join(os.path.basename(f) for f in data.files))
    L.append("SESI      : " + data.name)
    L.append("BASIS WAKTU: " + data.timebase)
    L.append("RENTANG   : %.2f s s/d %.2f s  (%d baris, durasi %.1f s)" % (t[0], t[-1], len(w), t[-1] - t[0]))
    L.append("LAJU      : median %.1f Hz | dt p95 %.0f ms | dt maks %.0f ms | celah > 2.5x median: %d"
             % (1.0 / med, np.percentile(dt, 95) * 1e3, dt.max() * 1e3, int((dt > 2.5 * med).sum())))
    if has(w, "seq"):
        g = np.diff(w["seq"].values) - 1
        L.append("FRAME HILANG (lompatan seq): %d (%.2f%%)" % (g[g > 0].sum(), 100.0 * g[g > 0].sum() / len(w)))
    L.append("KOLOM AKTIF: " + ", ".join(c for c in w.columns if c not in ("t", "waktu")))
    miss = [c for c in ("roll", "pitch", "yaw", "pps_rxd", "pps_lxd", "pps_r", "pps_l") if c not in w.columns]
    if miss:
        L.append("KOLOM TIDAK ADA: " + ", ".join(miss))
    segs = cmd_segments(w)
    L.append("PERINTAH  : %d perubahan; unik: %s" % (max(0, len(segs) - 1), ", ".join(sorted(set(s[0] for s in segs))) or "-"))
    if 1.0 / med < 15:
        L.append("\n! Laju data rendah (< 15 Hz). Cek koneksi serial / beban STM32.")
    if (dt > 2.5 * med).sum() > 0.02 * len(dt):
        L.append("! Banyak celah waktu (> 2%). Data ada yang hilang / thread serial tertahan.")
    rows = []
    for c in w.columns:
        if c in TIME_COLS or c in ("waktu", "cmd") or w[c].notna().sum() < 3:
            continue
        v = w[c].dropna()
        rows.append([c, len(v), fmt(v.mean(), 3), fmt(v.std(), 3), fmt(v.min(), 2), fmt(v.max(), 2)])
    L.append("\nSTATISTIK KOLOM\n" + table(["kolom", "n", "rata2", "std", "min", "maks"], rows))

    fig = new_fig(5.4)
    a1, a2 = fig.subplots(1, 2)
    a1.hist(dt * 1e3, bins=60, color="C0")
    a1.axvline(med * 1e3, color="r", ls="--", lw=1, label="median %.0f ms" % (med * 1e3))
    a1.set_xlabel("selang antar sampel [ms]")
    a1.set_ylabel("jumlah")
    a1.set_title("Distribusi selang waktu")
    a1.legend()
    bins = np.arange(t[0], t[-1] + 1.0, 1.0)
    cnt, _ = np.histogram(t, bins=bins)
    a2.plot(bins[:-1], cnt, lw=0.9)
    a2.axhline(1.0 / med, color="r", ls="--", lw=0.8)
    a2.set_xlabel("t [s]")
    a2.set_ylabel("sampel per detik")
    a2.set_title("Laju sampel (garis = median)")
    a2.grid(alpha=0.3)
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 2: IMU
# =====================================================================================
def _yaw_unwrapped(y):
    return np.degrees(np.unwrap(np.radians(np.asarray(y, dtype=float))))


def an_imu(data, opts):
    w = get_window(data, opts)
    names = [c for c in ("roll", "pitch", "yaw") if has(w, c)]
    if not names or len(w) < 5:
        return need(["roll/pitch/yaw"], "Kolom IMU tidak tersedia pada rentang ini.")
    n = len(names)
    sm_n = int(fnum(opts, "smooth", 1))
    segs = cmd_segments(w)
    p = ds(w)
    fig = new_fig(3.4 * n + 1.0)
    gs = GridSpec(n, 2, figure=fig, width_ratios=[3.4, 1])
    rows = []
    ax0 = None
    for i, c in enumerate(names):
        ax = fig.add_subplot(gs[i, 0], sharex=ax0) if ax0 is not None else fig.add_subplot(gs[i, 0])
        ax0 = ax0 or ax
        ax.plot(p["t"], p[c], lw=0.6, color="C%d" % i, alpha=0.5 if sm_n > 1 else 1.0)
        if sm_n > 1:
            ax.plot(p["t"], smooth(p[c], sm_n), lw=1.2, color="C%d" % i)
        mark_cmds(ax, segs, label=(i == 0))
        ax.set_ylabel(c + " [deg]")
        ax.grid(alpha=0.3)
        if i == n - 1:
            ax.set_xlabel("t [s]")
        axh = fig.add_subplot(gs[i, 1])
        axh.hist(w[c].dropna(), bins=40, orientation="horizontal", color="C%d" % i, alpha=0.8)
        axh.set_xlabel("jumlah")
        t = w["t"].values
        y = w[c].values.astype(float)
        yv = _yaw_unwrapped(y) if c == "yaw" else y
        ok = ~np.isnan(yv)
        if ok.sum() > 3 and t[ok][-1] > t[ok][0]:
            pf = np.polyfit(t[ok], yv[ok], 1)
            res = yv[ok] - np.polyval(pf, t[ok])
            dtt = np.diff(t[ok])
            rate = np.abs(np.diff(yv[ok]) / np.where(dtt > 0, dtt, np.nan))
            mean = (np.degrees(np.angle(np.mean(np.exp(1j * np.radians(y[ok]))))) if c == "yaw" else float(np.mean(yv[ok])))
            rows.append([c, fmt(mean), fmt(np.std(yv[ok]), 3), fmt(np.min(yv[ok]) if c != "yaw" else np.min(y[ok]), 1),
                         fmt(np.max(yv[ok]) if c != "yaw" else np.max(y[ok]), 1), fmt(np.ptp(yv[ok]), 2),
                         fmt(pf[0] * 60, 2), fmt(res.std(), 3), fmt(np.nanmax(rate), 1)])
    L = ["Statistik IMU pada rentang terpilih (yaw: rata-rata melingkar, std/drift dari yaw tanpa lompatan 360).\n",
         table(["sumbu", "rata2", "std", "min", "maks", "p-p", "drift[deg/mnt]", "noise*", "|laju|maks[deg/s]"], rows),
         "\n* noise = std setelah dikurangi tren linier.",
         "Garis putus-putus vertikal pada grafik = pergantian perintah (cmd)."]
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 2b: IMU SETPOINT (aktual vs setpoint)  dan  2c: ERROR SETPOINT
# =====================================================================================
# (label, kolom aktual, setpoint firmware, setpoint dari GUI, toleransi bawaan, melingkar?, satuan)
TRACK_CH = [
    ("yaw", "yaw", "sp_yaw", "gui_sp_yaw", 3.0, True, "deg"),
    ("pitch", "pitch", "sp_pitch", "gui_sp_pitch", 2.0, False, "deg"),
    ("roll", "roll", "sp_roll", "gui_sp_roll", 2.0, False, "deg"),
    ("nyelam", "z", "sp_z", "gui_sp_depth", 3.0, False, "cm"),
]


def pick_setpoint(w, fw, gui, mode="auto"):
    """Pilih kolom setpoint. auto: yang berubah (firmware diutamakan); bila keduanya konstan, firmware.
    Mengembalikan (nama_kolom | None, label_sumber)."""
    f_ok, g_ok = has(w, fw), has(w, gui)
    f_var = f_ok and w[fw].nunique() > 1
    g_var = g_ok and w[gui].nunique() > 1
    if mode == "firmware":
        return (fw, "GUI") if f_ok else (None, "")
    if mode == "GUI":
        return (gui, "GUI") if g_ok else (None, "")
    if f_var:
        return fw, "GUI"
    if g_var:
        return gui, "GUI"
    if f_ok:
        return fw, "GUI"
    if g_ok:
        return gui, "GUI"
    return None, ""


def _err_stats(e, tol):
    e = e[~np.isnan(e)]
    if len(e) < 3:
        return None
    return {"n": len(e), "mean": float(e.mean()), "std": float(e.std()), "rms": float(np.sqrt(np.mean(e ** 2))),
            "max": float(np.abs(e).max()), "inside": 100.0 * float(np.mean(np.abs(e) <= tol))}


def _track_items(w, opts):
    """Hitung aktual, setpoint, error, dan mask data tunak untuk tiap kanal yang punya setpoint."""
    mode = str(opts.get("track_src", "auto") or "auto")
    settle = fnum(opts, "track_settle", 5.0)
    tol_user = fnum(opts, "track_tol", 0.0)
    t = w["t"].values
    items = []
    for label, act, fw, gui, tol0, wrap, unit in TRACK_CH:
        if not has(w, act):
            continue
        col, src = pick_setpoint(w, fw, gui, mode)
        if col is None:
            continue
        tol = tol_user or tol0
        y = w[act].values.astype(float)
        sp = w[col].values.astype(float)
        e = wrap180(sp - y) if wrap else sp - y
        valid = ~(np.isnan(y) | np.isnan(sp))
        dsp = np.nan_to_num(np.abs(wrap180(np.diff(sp)) if wrap else np.diff(sp)))
        chg = np.where(dsp > 1e-6)[0] + 1
        tc = np.full(len(t), np.nan)
        tc[0] = t[0]
        tc[chg] = t[chg]
        steady = valid & ((t - pd.Series(tc).ffill().values) >= settle)
        items.append({"label": label, "act": act, "col": col, "src": src, "tol": tol, "wrap": wrap, "unit": unit,
                      "y": y, "sp": sp, "e": e, "valid": valid, "chg": chg, "steady": steady,
                      "st": _err_stats(e[steady], tol), "st_all": _err_stats(e[valid], tol)})
    return items, settle


def an_setpoint(data, opts):
    """Tab 'IMU Setpoint': HANYA aktual vs setpoint (yaw, pitch, roll, nyelam)."""
    w = get_window(data, opts)
    items, settle = _track_items(w, opts)
    if not items or len(w) < 10:
        return need(["roll/pitch/yaw/z dan sp_* atau gui_sp_*"], HINT_SP)
    t = w["t"].values
    segs = cmd_segments(w)
    n = len(items)
    sl = slice(None, None, max(1, len(w) // 15000))
    fig = new_fig(3.7 * n + 1.0)
    axs = np.atleast_1d(fig.subplots(n, 1, sharex=True))
    rows = []
    for i, (ax, it) in enumerate(zip(axs, items)):
        ax.plot(t[sl], it["y"][sl], lw=1.4, color="C%d" % i, label="aktual")
        ax.step(t[sl], it["sp"][sl], where="post", color="k", ls="--", lw=1.5, label="setpoint (%s)" % it["src"])
        ax.set_ylabel("%s [%s]" % (it["label"], it["unit"]))
        ax.set_title("%s: imu setpoint" % it["label"].upper(), loc="left")
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right")
        mark_cmds(ax, segs, label=(i == 0))
        sp = it["sp"][~np.isnan(it["sp"])]
        y = it["y"][~np.isnan(it["y"])]
        rows.append([it["label"], "%s (%s)" % (it["src"], it["col"]), "%.1f .. %.1f" % (sp.min(), sp.max()),
                     len(it["chg"]), "%.1f .. %.1f" % (y.min(), y.max()), it["unit"]])
    axs[-1].set_xlabel("t [s]")
    L = ["GRAFIK: aktual (garis berwarna) vs setpoint (garis putus-putus hitam). Garis titik-titik vertikal = pergantian perintah (cmd).",
         "",
         table(["kanal", "acuan setpoint", "rentang setpoint", "jumlah perubahan", "rentang aktual", "satuan"], rows),
         ""]
    return fig, "\n".join(L)


def an_error(data, opts):
    """Tab 'Error Setpoint': error = setpoint - aktual, statistik tunak, per tahapan, per perintah, saran."""
    w = get_window(data, opts)
    items, settle = _track_items(w, opts)
    if not items or len(w) < 10:
        return need(["roll/pitch/yaw/z dan sp_* atau gui_sp_*"], HINT_SP)
    t = w["t"].values
    cmds = w["cmd"].values
    n = len(items)
    sl = slice(None, None, max(1, len(w) // 15000))
    fig = new_fig(3.5 * n + 1.0)
    gs = GridSpec(n, 2, figure=fig, width_ratios=[3.4, 1])
    first = None
    sum_rows, hold_rows, cmd_rows, advice = [], [], [], []
    for i, it in enumerate(items):
        label, unit, tol, e, steady, st, st_all = it["label"], it["unit"], it["tol"], it["e"], it["steady"], it["st"], it["st_all"]
        sp, src, col = it["sp"], it["src"], it["col"]
        sp_range = (np.nanmin(sp), np.nanmax(sp))
        sum_rows.append([label, src + " (" + col + ")", "%.1f..%.1f" % sp_range, st["n"] if st else 0,
                         fmt(st["mean"], 2) if st else "-", fmt(st["std"], 2) if st else "-", fmt(st["rms"], 2) if st else "-",
                         fmt(st["max"], 1) if st else "-", (fmt(st["inside"], 0) + "%") if st else "-",
                         fmt(st_all["rms"], 2) if st_all else "-", "%.1f %s" % (tol, unit)])
        bounds = np.r_[0, it["chg"], len(t)]
        for k in range(len(bounds) - 1):
            a, b = bounds[k], bounds[k + 1]
            if b - a < 2 or t[b - 1] - t[a] < settle + 2:
                continue
            m = np.zeros(len(t), dtype=bool)
            m[a:b] = True
            s2 = _err_stats(e[m & steady], tol)
            if s2 and len(hold_rows) < 40:
                hold_rows.append([label, "%.1f" % sp[a], "%.1f-%.1f" % (t[a], t[b - 1]), fmt(t[b - 1] - t[a], 1),
                                  fmt(s2["mean"], 2), fmt(s2["rms"], 2), fmt(s2["inside"], 0) + "%"])
        for c in sorted(set(cmds)):
            s3 = _err_stats(e[steady & (cmds == c)], tol)
            if s3 and s3["n"] >= 10:
                cmd_rows.append([label, c, s3["n"], fmt(s3["mean"], 2), fmt(s3["rms"], 2), fmt(s3["inside"], 0) + "%"])
        if not st or st["n"] < 20:
            advice.append("%s: data tunak terlalu sedikit (< 20 sampel). Tahan setpoint lebih lama atau kecilkan 'Setelah ubah setpoint'." % label)
        else:
            if abs(st["mean"]) > 0.5 * tol:
                advice.append("%s: bias tunak %+.2f %s (aktual %s setpoint). Cek offset IMU (tab Analisis Statis), trim "
                              "(mis. ROLLTRIM), atau tambah Ki/feedforward." % (label, st["mean"], unit, "di bawah" if st["mean"] > 0 else "di atas"))
            if st["std"] > 0.5 * tol:
                advice.append("%s: error berfluktuasi (std %.2f %s): ada ayunan/noise, atau transien belum selesai "
                              "(sumbu lambat seperti nyelam: naikkan 'Setelah ubah setpoint'). Lihat tab Respons Langkah dan Analisis Statis."
                              % (label, st["std"], unit))
            if st["inside"] < 80:
                advice.append("%s: hanya %.0f%% waktu dalam toleransi +-%.1f %s." % (label, st["inside"], tol, unit))
            if abs(st["mean"]) <= 0.5 * tol and st["std"] <= 0.5 * tol and st["inside"] >= 80:
                advice.append("%s: mengikuti setpoint dengan baik (bias %+.2f, RMS %.2f %s, %.0f%% dalam toleransi)." % (label, st["mean"], st["rms"], unit, st["inside"]))
        if sp_range[1] - sp_range[0] < 1e-6:
            advice.append("%s: setpoint tidak berubah di rentang ini (%.1f), jadi angka di atas = kemampuan MENAHAN setpoint." % (label, sp[0]))
        # --- grafik: error (kiri) + sebaran (kanan)
        ax = fig.add_subplot(gs[i, 0], sharex=first) if first is not None else fig.add_subplot(gs[i, 0])
        first = first or ax
        ax.axhspan(-tol, tol, color="green", alpha=0.13, label="toleransi +-%.1f" % tol)
        ax.fill_between(t, 0, 1, where=~steady, transform=ax.get_xaxis_transform(), color="0.7", alpha=0.35, step="post",
                        label="transien (tidak dihitung)")
        ax.axhline(0, color="k", lw=0.8)
        ax.plot(t[sl], e[sl], lw=1.2, color="C3", label="error = setpoint - aktual")
        ax.set_ylabel("error %s [%s]" % (label, unit))
        ea = np.abs(e[steady & ~np.isnan(e)])
        title = "ERROR %s" % label.upper()
        lim = None
        if len(ea) >= 20:
            lim = max(3.0 * tol, 3.0 * float(np.percentile(ea, 99)))     # fokus ke data tunak; lonjakan transien dipotong
            ax.set_ylim(-lim, lim)
            title += "   (skala mengikuti data tunak; lonjakan transien terpotong, gunakan zoom untuk melihatnya)"
        ax.set_title(title, loc="left")
        ax.grid(alpha=0.3)
        if i == 0:
            ax.legend(loc="upper right")
        if i == n - 1:
            ax.set_xlabel("t [s]")
        axh = fig.add_subplot(gs[i, 1])
        es = e[steady]
        es = es[~np.isnan(es)]
        if len(es):
            axh.hist(es, bins=40, orientation="horizontal", color="C3", alpha=0.8)
        axh.axhline(0, color="k", lw=0.8)
        axh.axhline(tol, color="g", ls="--", lw=1)
        axh.axhline(-tol, color="g", ls="--", lw=1)
        if lim is not None:
            axh.set_ylim(-lim, lim)
        axh.set_xlabel("jumlah (data tunak)")
        axh.set_title("sebaran error", loc="left")
    L = ["Error = setpoint - aktual (positif: aktual di bawah setpoint).",
         "Metrik 'tunak' hanya memakai data >= %.0f s setelah setpoint terakhir berubah (area abu-abu = transien, tidak dihitung)." % settle,
         "",
         "RINGKASAN PER KANAL (bias/std/RMS/maks dari data tunak)",
         table(["kanal", "acuan setpoint", "rentang sp", "n", "bias", "std", "RMS", "maks|e|", "dalam tol.", "RMS(semua)", "toleransi"], sum_rows)]
    if hold_rows:
        L.append("\nPER TAHAPAN SETPOINT (data tunak setiap setpoint yang ditahan >= %.0f s)" % (settle + 2))
        L.append(table(["kanal", "setpoint", "waktu[s]", "durasi", "bias", "RMS", "dalam tol."], hold_rows))
    if cmd_rows:
        L.append("\nPER PERINTAH (perintah mana yang benar-benar mengikuti setpoint)")
        L.append(table(["kanal", "cmd", "n", "bias", "RMS", "dalam tol."], cmd_rows[:40]))
    L.append("\nKESIMPULAN / SARAN")
    L += ["- " + a for a in advice]
    L.append("\nCatatan: bila acuan = 'GUI', setpoint adalah yang DIPERINTAHKAN lewat tombol GUI. Perintah tertentu "
             "(mis. STANDBY) bisa tidak memakai setpoint itu, sehingga error besar belum tentu PID buruk; lihat tabel per perintah. "
             "Setpoint firmware (sp_*) bisa berbeda karena trim di firmware.")
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 3: PPS
# =====================================================================================
def an_pps(data, opts):
    w = get_window(data, opts)
    th = active_thrusters(w)
    if not th or len(w) < 5:
        return need(["pps_rxd/pps_lxd/pps_r/pps_l"], "Kolom PPS tidak tersedia pada rentang ini.")
    sm_n = int(fnum(opts, "smooth", 1))
    segs = cmd_segments(w)
    p = ds(w)
    fig = new_fig(11.5)
    gs = GridSpec(3, 2, figure=fig, height_ratios=[2.2, 1.2, 1.6], width_ratios=[3, 1.2])
    ax1 = fig.add_subplot(gs[0, :])
    for i, t in enumerate(th):
        ax1.plot(p["t"], smooth(p["pps_" + t], sm_n), lw=0.9, label=t.upper())
    mean_all = w[["pps_" + t for t in th]].mean(axis=1)
    pm = ds(pd.DataFrame({"t": w["t"], "m": mean_all}))
    ax1.plot(pm["t"], pm["m"], "k--", lw=0.8, label="rata-rata")
    mark_cmds(ax1, segs, label=True)
    ax1.set_ylabel("PPS")
    ax1.set_xlabel("t [s]")
    ax1.legend(ncol=5, fontsize=10)
    ax1.grid(alpha=0.3)
    arr = np.vstack([w["pps_" + t].values for t in th])
    mean = np.nanmean(arr, axis=0)
    spread = np.nanmax(arr, axis=0) - np.nanmin(arr, axis=0)
    imb = np.where(mean > 5, spread / np.where(mean > 0, mean, np.nan) * 100.0, np.nan)
    ax2 = fig.add_subplot(gs[1, :], sharex=ax1)
    pi = pd.DataFrame({"t": w["t"], "i": imb})
    pi = ds(pi)
    ax2.plot(pi["t"], pi["i"], lw=0.8, color="C3")
    ax2.set_ylabel("ketidakseimbangan [%]")
    ax2.set_xlabel("t [s]")
    ax2.grid(alpha=0.3)
    ax3 = fig.add_subplot(gs[2, 0])
    vals = [w["pps_" + t].values[w["pps_" + t].values > 2] for t in th]
    if any(len(v) for v in vals):
        try:
            ax3.boxplot([v if len(v) else [np.nan] for v in vals], tick_labels=[t.upper() for t in th])
        except TypeError:                       # matplotlib < 3.9
            ax3.boxplot([v if len(v) else [np.nan] for v in vals], labels=[t.upper() for t in th])
    ax3.set_ylabel("PPS (saat aktif, > 2)")
    ax3.set_title("Sebaran PPS per thruster", fontsize=10)
    ax3.grid(alpha=0.3)
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.bar([t.upper() for t in th], [100.0 * np.mean(w["pps_" + t].values > 2) for t in th], color="C2")
    ax4.set_ylabel("% waktu aktif")
    ax4.set_title("Aktif (PPS > 2)", fontsize=10)

    rows = []
    for t in th:
        v = w["pps_" + t].values
        a = v[v > 2]
        rows.append([t.upper(), fmt(a.mean() if len(a) else np.nan, 1), fmt(a.std() if len(a) else np.nan, 1),
                     fmt(np.nanmax(v), 1), fmt(100.0 * np.mean(v > 2), 0) + "%"])
    L = ["PPS per thruster (rata-rata/std hanya saat aktif, PPS > 2)\n", table(["thruster", "rata2", "std", "maks", "aktif"], rows)]
    ib = imb[~np.isnan(imb)]
    if len(ib):
        L.append("\nKetidakseimbangan antar thruster saat bergerak: rata-rata %.1f%%, median %.1f%%, p95 %.1f%%"
                 % (ib.mean(), np.median(ib), np.percentile(ib, 95)))
        if np.median(ib) > 15:
            L.append("! > 15%: thruster tidak seragam (trim PWM / hall / baling-baling). Cek analisis PWM-PPS bila ada kolom pwm_*.")
    for t in th:
        v = w["pps_" + t].values
        if np.mean(v > 2) < 0.02 and np.mean(mean > 10) > 0.2:
            L.append("! %s hampir selalu 0 padahal thruster lain aktif: kemungkinan hall sensor / kabel / thruster bermasalah." % t.upper())
    cr = []
    for c in sorted(set(s[0] for s in segs)):
        m = (w["cmd"] == c).values
        cr.append([c, int(m.sum()), fmt(np.nanmean(mean[m]), 1), fmt(np.nanmean(imb[m]) if np.any(~np.isnan(imb[m])) else np.nan, 1)])
    L.append("\nPER PERINTAH\n" + table(["cmd", "n", "PPS rata2", "ketidakseimbangan %"], cr))
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 4: PERINTAH (CMD)
# =====================================================================================
def an_cmd(data, opts):
    w = get_window(data, opts)
    if len(w) < 5:
        return None, "Rentang terlalu pendek."
    segs = cmd_segments(w)
    uniq = []
    for c, _, _ in segs:
        if c not in uniq:
            uniq.append(c)
    tab20 = colormaps["tab20"]
    colors = {c: tab20(i % 20) for i, c in enumerate(uniq)}
    th = active_thrusters(w)
    nrows = 1 + int(has(w, "yaw")) + int(bool(th))
    fig = new_fig(2.4 + 3.3 * nrows)
    ratios = [max(1.0, 0.45 * len(uniq))] + [2.2] * (nrows - 1)
    axs = fig.subplots(nrows, 1, sharex=True, gridspec_kw={"height_ratios": ratios})
    axs = np.atleast_1d(axs)
    g = axs[0]
    for c, a, b in segs:
        yi = uniq.index(c)
        g.broken_barh([(a, max(b - a, 0.02))], (yi - 0.4, 0.8), facecolors=colors[c])
    g.set_yticks(range(len(uniq)))
    g.set_yticklabels(uniq, fontsize=10)
    g.set_ylim(-0.7, len(uniq) - 0.3)
    g.invert_yaxis()
    g.set_title("Linimasa perintah GUI", fontsize=10)
    g.grid(alpha=0.3, axis="x")
    k = 1
    if has(w, "yaw"):
        p = ds(w)
        axs[k].plot(p["t"], p["yaw"], lw=0.8, color="C2")
        mark_cmds(axs[k], segs)
        axs[k].set_ylabel("yaw [deg]")
        axs[k].grid(alpha=0.3)
        k += 1
    if th:
        m = w[["pps_" + t for t in th]].mean(axis=1)
        q = ds(pd.DataFrame({"t": w["t"], "m": m}))
        axs[k].plot(q["t"], q["m"], lw=0.9, color="C1")
        mark_cmds(axs[k], segs)
        axs[k].set_ylabel("PPS rata-rata")
        axs[k].grid(alpha=0.3)
    axs[-1].set_xlabel("t [s]")

    agg = {}
    for c, a, b in segs:
        m = ((w["t"] >= a) & (w["t"] <= b) & (w["cmd"] == c)).values
        if m.sum() < 2:
            continue
        r = agg.setdefault(c, {"seg": 0, "dur": 0.0, "pps": [], "yaw": []})
        r["seg"] += 1
        r["dur"] += b - a
        if th:
            r["pps"].append(float(w.loc[m, ["pps_" + t for t in th]].mean(axis=1).mean()))
        if has(w, "yaw"):
            yy = _yaw_unwrapped(w.loc[m, "yaw"].values)
            r["yaw"].append(float(np.std(yy)))
    rows = [[c, r["seg"], fmt(r["dur"], 1), fmt(np.mean(r["pps"]) if r["pps"] else np.nan, 1),
             fmt(np.mean(r["yaw"]) if r["yaw"] else np.nan, 2)] for c, r in sorted(agg.items(), key=lambda kv: -kv[1]["dur"])]
    L = ["RINGKASAN PER PERINTAH (urut dari terlama)\n", table(["cmd", "segmen", "durasi total[s]", "PPS rata2", "std yaw[deg]"], rows)]
    srows = [[i + 1, c, fmt(a, 2), fmt(b, 2), fmt(b - a, 2)] for i, (c, a, b) in enumerate(segs[:60])]
    L.append("\nDAFTAR SEGMEN" + (" (60 pertama)" if len(segs) > 60 else "") + "\n" +
             table(["no", "cmd", "mulai[s]", "akhir[s]", "durasi[s]"], srows))
    L.append("\nCatatan: cmd = perintah GUI terakhir yang dikirim, bukan keadaan aktif di STM32.")
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 5: STATIS (IMU diam)
# =====================================================================================
def an_static(data, opts):
    w = get_window(data, opts)
    s0, s1 = fnum(opts, "s0", None), fnum(opts, "s1", None)
    if s0 is not None:
        w = w[w["t"] >= s0]
    if s1 is not None:
        w = w[w["t"] <= s1]
    w = w.reset_index(drop=True)
    names = [c for c in ("roll", "pitch", "yaw") if has(w, c)]
    if not names or len(w) < 20:
        return need(["roll/pitch/yaw"], "Pilih jendela >= beberapa detik saat AUV diam (thruster mati), mis. Mulai 5, Akhir 305.")
    t = w["t"].values
    dur = t[-1] - t[0]
    fs = 1.0 / float(np.median(np.diff(t)))
    L = ["Jendela %.1f s - %.1f s (%.1f s, %d sampel, ~%.1f Hz)" % (t[0], t[-1], dur, len(w), fs)]
    th = active_thrusters(w)
    if th:
        mx = max(np.nanmax(w["pps_" + x].values) for x in th)
        if mx > 3:
            L.append("! PPS maks %.1f di jendela ini: thruster tampak aktif, ini bukan tes diam murni." % mx)
    if (w["cmd"] != "CMD_STOP").any() and w["cmd"].nunique() > 1:
        L.append("! Ada perubahan perintah di jendela: %s" % ", ".join(sorted(w["cmd"].unique())))
    n = len(names)
    fig = new_fig(9.5)
    gs = GridSpec(2, n, figure=fig)
    rows = []
    for i, c in enumerate(names):
        y = w[c].values.astype(float)
        yv = _yaw_unwrapped(y) if c == "yaw" else y
        pf = np.polyfit(t, yv, 1)
        res = yv - np.polyval(pf, t)
        rows.append([c, fmt(np.mean(yv) if c != "yaw" else np.degrees(np.angle(np.mean(np.exp(1j * np.radians(y))))), 3),
                     fmt(yv.std(), 3), fmt(np.ptp(yv), 2), fmt(pf[0] * 60, 3), fmt(res.std(), 3)])
        ax = fig.add_subplot(gs[0, i])
        ax.plot(t, yv, lw=0.7, color="C%d" % i)
        ax.plot(t, np.polyval(pf, t), "r--", lw=1, label="tren %.2f deg/mnt" % (pf[0] * 60))
        ax.set_title(c, fontsize=10)
        ax.set_xlabel("t [s]")
        ax.set_ylabel("deg")
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        ax2 = fig.add_subplot(gs[1, i])
        if len(res) >= 64:
            win = np.hanning(len(res))
            sp = np.abs(np.fft.rfft(res * win)) * 2.0 / win.sum()
            fr = np.fft.rfftfreq(len(res), 1.0 / fs)
            ax2.semilogy(fr[1:], sp[1:] + 1e-9, lw=0.8, color="C%d" % i)
            ax2.set_xlabel("frekuensi [Hz]")
            ax2.set_ylabel("amplitudo [deg]")
            ax2.set_title("Spektrum noise " + c, fontsize=10)
            ax2.grid(alpha=0.3, which="both")
    L.append("\n" + table(["sumbu", "rata2[deg]", "std", "p-p", "drift[deg/mnt]", "noise*"], rows))
    L.append("* noise = std setelah dikurangi tren linier.\n")
    for r in rows:
        if r[0] in ("roll", "pitch"):
            L.append("- %s: posisi diam rata-rata %s deg. Bila seharusnya datar -> tambah %s_offset sebesar %+.2f; "
                     "bila memang trim badan (CG/buoyancy), jadikan setpoint trim (%s)."
                     % (r[0], r[1], r[0], float(r[1]), "ROLLTRIM / ROLLTRIMMJ" if r[0] == "roll" else "SetpointPITCH"))
        else:
            d = float(r[4])
            L.append("- yaw: drift %.2f deg/menit saat diam. %s" % (
                d, "Baik (< 1 deg/menit)." if abs(d) < 1 else
                "> 1 deg/menit: cek kalibrasi BNO055 (mag = 3) dan gangguan magnet; jauhkan kabel arus besar."))
    L.append("\nSpektrum: puncak tajam di frekuensi tertentu menandakan getaran (thruster/pompa/struktur); "
             "noise datar = noise sensor.")
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 6: RESPONS LANGKAH (butuh sp_* [dan o_*])
# =====================================================================================
def _crossings(e, h):
    last, idx = 0, []
    for i, v in enumerate(e):
        if abs(v) <= h:
            continue
        sg = 1 if v > 0 else -1
        if last and sg != last:
            idx.append(i)
        last = sg
    return idx


def _step_metrics(t, y, sp, o, step, is_yaw, tol, y0):
    e = wrap180(sp - y) if is_yaw else sp - y
    prog = (wrap180(y - y0) if is_yaw else y - y0) / step
    band = max(tol, 0.02 * abs(step))
    m = {"step": step}
    i10 = int(np.argmax(prog >= 0.1)) if (prog >= 0.1).any() else None
    i90 = int(np.argmax(prog >= 0.9)) if (prog >= 0.9).any() else None
    m["rise"] = (t[i90] - t[i10]) if (i10 is not None and i90 is not None and i90 > i10) else np.nan
    m["delay"] = (t[i10] - t[0]) if i10 is not None else np.nan
    m["os"] = max(0.0, prog.max() - 1.0) * 100
    out = np.abs(e) > band
    if out[-1]:
        m["settle"] = np.nan
    else:
        last = np.where(out)[0]
        m["settle"] = (t[last[-1] + 1] - t[0]) if len(last) else 0.0
    m["sse"] = float(e[int(0.8 * len(e)):].mean())
    m["iae"] = float(trapz(np.abs(e), t))
    m["tu"], m["decay"], m["zc"] = np.nan, np.nan, 0
    if i90 is not None:
        ee, tt = e[i90:], t[i90:]
        idx = _crossings(ee, 0.5 * band)
        m["zc"] = len(idx)
        if len(idx) >= 3:
            m["tu"] = 2 * float(np.median(np.diff(tt[idx])))
        if len(idx) >= 2:
            edges = list(idx) + [len(ee)]
            pk = [np.abs(ee[a:b]).max() for a, b in zip(edges[:-1], edges[1:])]
            pk = [x for x in pk if x > 0.5 * band]
            if len(pk) >= 2:
                m["decay"] = pk[1] / pk[0]
    m["chatter"] = float(np.nanstd(np.diff(o))) if o is not None and len(o) > 3 else np.nan
    return m


def _advice(ms, ch):
    def med(k):
        v = [m[k] for m in ms if not np.isnan(m[k])]
        return float(np.median(v)) if v else np.nan
    os_, sse, rise, dec = med("os"), med("sse"), med("rise"), med("decay")
    tips = []
    if np.median([m["zc"] for m in ms]) >= 4 and (np.isnan(dec) or dec > 0.8):
        tips.append("Osilasi bertahan (decay %s): Kp terlalu besar atau ada delay. Turunkan Kp ~30%%, naikkan Kd." % fmt(dec))
    elif os_ > 15 or (np.median([m["zc"] for m in ms]) >= 4 and dec > 0.4):
        tips.append("Overshoot %.0f%% / berayun (decay %s): naikkan Kd ~20-50%% atau turunkan Kp ~20%%; kecilkan Ki. "
                    "Target awal: overshoot < 10-15%%." % (os_, fmt(dec)))
    elif os_ < 5 and (np.isnan(rise) or rise > 2.0) and abs(sse) < 2:
        tips.append("Respons lambat tanpa overshoot (rise %s s): naikkan Kp ~20-40%%." % fmt(rise, 1))
    if abs(sse) > (3.0 if ch == "yaw" else 2.0) and (np.isnan(os_) or os_ < 15):
        tips.append("Error tunak %.1f tanpa osilasi: naikkan Ki sedikit (5-10%% Kp) atau perbaiki trim/feedforward." % sse)
    if med("chatter") > 15:
        tips.append("Output bergetar (chatter tinggi): Kd terlalu besar terhadap noise -> turunkan Kd / filter D.")
    return tips or ["Tidak ada masalah dominan dari metrik. Uji ulang di kondisi lain (kecepatan, baterai, arus air)."]


def an_step(data, opts):
    ch = str(opts.get("step_ch", "yaw") or "yaw")
    w = get_window(data, opts)
    sp_c, o_c = "sp_" + ch, "o_" + ch
    sp_note = "setpoint (%s)" % sp_c
    alt = GUI_SP.get(ch)
    fw_varies = has(w, sp_c) and w[sp_c].nunique() > 1
    if not fw_varies and alt and has(w, alt) and w[alt].nunique() > 1:
        # firmware lama tidak mencetak setpoint yaw (selalu 0.0) -> pakai setpoint yang diperintahkan GUI
        sp_c = alt
        sp_note = "setpoint perintah GUI (%s); setpoint firmware tidak berubah/tidak ada" % alt
    if not has(w, ch, sp_c):
        return need([ch, sp_c], HINT_SP)
    is_yaw = ch == "yaw"
    ms_step = fnum(opts, "step_min", 0) or (10.0 if ch in ("yaw", "z") else 5.0)
    tol = fnum(opts, "step_tol", 0) or {"yaw": 3.0, "z": 3.0, "pitch": 2.0, "roll": 2.0}[ch]
    hold, maxwin = fnum(opts, "step_hold", 4.0), fnum(opts, "step_win", 30.0)
    t, y, sp = w["t"].values, w[ch].values.astype(float), w[sp_c].values.astype(float)
    o = w[o_c].values.astype(float) if has(w, o_c) else None
    chg = np.where(np.abs(np.diff(wrap180(sp) if is_yaw else sp)) > 1e-6)[0] + 1
    bounds = np.r_[0, chg, len(t)]
    res, segs = [], []
    for k in range(1, len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        b = min(b, int(np.searchsorted(t, t[a] + maxwin)))
        prev = sp[bounds[k] - 1]
        step = wrap180(sp[a] - prev) if is_yaw else sp[a] - prev
        if abs(step) < ms_step or t[b - 1] - t[a] < hold:
            continue
        pre = (t >= t[a] - 0.5) & (t < t[a])
        if pre.any():
            y0 = (np.degrees(np.angle(np.mean(np.exp(1j * np.radians(y[pre]))))) if is_yaw else float(np.median(y[pre])))
        else:
            y0 = y[a - 1]
        m = _step_metrics(t[a:b], y[a:b], sp[a], None if o is None else o[a:b], step, is_yaw, tol, y0)
        res.append(m)
        segs.append((a, b))
    if not res:
        return None, ("Tidak ada langkah setpoint >= %.0f dengan durasi >= %.0f s pada kanal %s.\n"
                      "Ubah 'Min langkah' / 'Tahan min' atau lakukan tes langkah (mis. yaw 0 -> 30 -> -30)." % (ms_step, hold, ch))
    show = list(zip(res, segs))[:6]
    fig = new_fig(3.5 * len(show) + 0.8)
    axs = np.atleast_1d(fig.subplots(len(show), 1, squeeze=False)[:, 0])
    for ax, (m, (a, b)) in zip(axs, show):
        ax.plot(t[a:b] - t[a], y[a:b], label=ch)
        ax.plot(t[a:b] - t[a], sp[a:b], "k--", lw=0.8, label="setpoint")
        ax.set_ylabel(ch)
        ax.grid(alpha=0.3)
        if o is not None:
            ax2 = ax.twinx()
            ax2.plot(t[a:b] - t[a], o[a:b], "C3", lw=0.6, alpha=0.6)
            ax2.set_ylabel("output PID", color="C3")
        ax.set_title("langkah %+.1f | overshoot %s%% | settle %s s" % (m["step"], fmt(m["os"], 1), fmt(m["settle"])), fontsize=10)
    axs[-1].set_xlabel("t sejak langkah [s]")
    rows = [[i + 1, "%+.1f" % m["step"], fmt(m["delay"]), fmt(m["rise"]), fmt(m["os"], 1), fmt(m["settle"]),
             fmt(m["sse"]), fmt(m["iae"], 1), m["zc"], fmt(m["tu"]), fmt(m["decay"])] for i, m in enumerate(res)]
    L = ["Respons langkah kanal %s (%d langkah; grafik menampilkan maks 6). Acuan: %s\n" % (ch, len(res), sp_note),
         table(["#", "langkah", "delay[s]", "rise10-90[s]", "overshoot[%]", "settle[s]", "err tunak", "IAE", "zero-cross", "Tu[s]", "decay"], rows),
         "\nSARAN (heuristik; ubah SATU gain per percobaan, ulangi tes yang sama):"]
    L += ["- " + tip for tip in _advice(res, ch)]
    return fig, "\n".join(L)


# =====================================================================================
#  ANALISIS 7: PWM -> PPS (butuh pwm_*)
# =====================================================================================
def an_pwm(data, opts):
    w = get_window(data, opts)
    th = [t for t in THR if has(w, "pwm_" + t, "pps_" + t)]
    if not th:
        return need(["pwm_*", "pps_*"], HINT_PWM)
    settle = fnum(opts, "settle", 2.0)
    ref = fnum(opts, "ref_pwm", 1700.0)
    rate = len(w) / max(w["t"].iloc[-1] - w["t"].iloc[0], 1e-6)
    n = max(5, int(settle * rate))
    fig = new_fig(10.0)
    axs = np.atleast_1d(fig.subplots(2, 2)).ravel()
    L, ref_pps, ms = [], {}, []
    for ax, t in zip(axs, th):
        pw, pp = w["pwm_" + t], w["pps_" + t]
        steady = (pw.rolling(n).std() < 3) & (pp.rolling(n).std() < np.maximum(2.0, 0.08 * pp.rolling(n).mean().fillna(0)))
        s = w[steady & (pw - 1500).abs().gt(40)]
        ax.set_title(t.upper(), fontsize=10)
        ax.set_xlabel("PWM [us]")
        ax.set_ylabel("PPS")
        ax.grid(alpha=0.3)
        ax.scatter(pw, pp, s=2, c="0.8")
        if len(s) < 10:
            L.append("- %s: data steady-state kurang (%d titik). Lakukan tangga PWM, tiap level >= %.0f s." % (t.upper(), len(s), settle + 3))
            continue
        b = s.assign(bin=(s["pwm_" + t] / 10).round() * 10).groupby("bin")["pps_" + t].agg(["median", "count"])
        b = b[b["count"] >= 3]
        ax.scatter(b.index, b["median"], c="C1", s=25, zorder=3)
        for name, sel, code in (("maju", b.index > 1500, CODE_PPS_FWD), ("mundur", b.index < 1500, CODE_PPS_REV)):
            bb = b[sel]
            if len(bb) < 3:
                continue
            m, c = np.polyfit(bb.index.values, bb["median"].values, 1)
            pred = m * bb.index.values + c
            r2 = 1 - ((bb["median"].values - pred) ** 2).sum() / max(((bb["median"].values - bb["median"].mean()) ** 2).sum(), 1e-9)
            xs = np.array([bb.index.min(), bb.index.max()])
            ax.plot(xs, m * xs + c, "C3", lw=1)
            ax.plot(xs, code[0] * xs + code[1], "k--", lw=0.8)
            L.append("- %s %s: pps = %.4f*pwm %+.1f  (R2=%.3f)  | firmware sekarang: %.3f*pwm %+.1f" % (t.upper(), name, m, c, r2, code[0], code[1]))
            if name == "maju":
                ref_pps[t] = m * ref + c
                ms.append(m)
    if len(ref_pps) >= 2:
        mean_pps = np.mean(list(ref_pps.values()))
        mm = np.mean(ms)
        L.append("\nPPS prediksi pada PWM %d: " % ref + ", ".join("%s=%.1f" % (k.upper(), v) for k, v in ref_pps.items()))
        L.append("Saran hallTrimUs[] (urutan RXD,LXD,R,L): {" + ", ".join(
            str(int(round((mean_pps - ref_pps.get(t, mean_pps)) / mm))) for t in THR) + "}")
    return fig, "REGRESI PWM -> PPS (titik oranye = median per level; merah = regresi; hitam putus = nilai di firmware)\n\n" + "\n".join(L)


# =====================================================================================
#  ANALISIS 8: JARAK / LINTASAN (butuh pul_*, x, y)
# =====================================================================================
def an_dist(data, opts):
    w = get_window(data, opts)
    pul = [t for t in THR if has(w, "pul_" + t)]
    xy = has(w, "x", "y")
    if not pul and not xy:
        return need(["pul_*", "x", "y"], HINT_DIST)
    ncol = int(xy) + int(bool(pul))
    fig = new_fig(7.0)
    axs = np.atleast_1d(fig.subplots(1, ncol))
    k = 0
    L = []
    if xy:
        ax = axs[k]
        k += 1
        p = ds(w)
        sc = ax.scatter(p["x"], p["y"], c=p["t"], s=4, cmap="viridis")
        ax.plot(p["x"].iloc[0], p["y"].iloc[0], "go", label="awal")
        ax.plot(p["x"].iloc[-1], p["y"].iloc[-1], "rs", label="akhir")
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel("X [m]")
        ax.set_ylabel("Y [m]")
        ax.set_title("Lintasan (odometri pulsa + yaw, bukan posisi sebenarnya)", fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=10)
        fig.colorbar(sc, ax=ax, label="t [s]")
        L.append("Lintasan: jarak garis lurus awal-akhir %.2f m" % np.hypot(w["x"].iloc[-1] - w["x"].iloc[0], w["y"].iloc[-1] - w["y"].iloc[0]))
    if pul:
        ax = axs[k]
        p = ds(w)
        for t in pul:
            ax.plot(p["t"], p["pul_" + t], lw=0.9, label=t.upper())
        ax.set_xlabel("t [s]")
        ax.set_ylabel("pulsa kumulatif")
        ax.set_title("Pulsa hall per thruster", fontsize=10)
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        d = {t: float(w["pul_" + t].iloc[-1] - w["pul_" + t].iloc[0]) for t in pul}
        if min(d.values()) < 0:
            L.append("! Counter turun di rentang ini (CMD_RST di tengah?). Pilih rentang tanpa reset.")
        avg = float(np.mean(list(d.values())))
        L.append("Pulsa pada rentang: " + ", ".join("%s=%d" % (k2.upper(), v) for k2, v in d.items()))
        if avg > 0:
            L.append("Selisih antar-thruster %.1f%% (besar = trim/hall tidak seragam)" % ((max(d.values()) - min(d.values())) / avg * 100))
            known = fnum(opts, "known", 0.0)
            if known > 0:
                mf = known / avg
                L.append("Jarak nyata %.2f m / %.1f pulsa rata-rata -> mf = %.6f m/pulsa (firmware %.6f; selisih %+.1f%%)"
                         % (known, avg, mf, CODE_MF, (mf / CODE_MF - 1) * 100))
                L.append("Ulangi >= 5 kali dan ambil median. Atur rentang waktu agar hanya mencakup satu lintasan lurus.")
            else:
                L.append("Isi 'Jarak nyata (m)' lalu Hitung untuk kalibrasi mf (rentang waktu = satu lintasan lurus).")
    return fig, "\n".join(L)


# =====================================================================================
#  DAFTAR ANALISIS
#  (nama tab, fungsi, [(label, kunci opsi, nilai bawaan, lebar entry | "combo:a,b,c"), ...])
# =====================================================================================
TABS = [
    ("Ringkasan", an_summary, []),
    ("IMU", an_imu, []),
    ("IMU Setpoint", an_setpoint, [("Acuan setpoint", "track_src", "auto", "combo:auto,firmware,GUI")]),
    ("Error Setpoint", an_error, [("Acuan setpoint", "track_src", "auto", "combo:auto,firmware,GUI"),
                                  ("Toleransi", "track_tol", "0", 6), ("Setelah ubah setpoint (s)", "track_settle", "5", 5)]),
    ("PPS", an_pps, []),
    ("Perintah (CMD)", an_cmd, []),
    ("Analisis Statis", an_static, [("Mulai (s)", "s0", "", 7), ("Akhir (s)", "s1", "", 7)]),
    ("Respons Langkah", an_step, [("Kanal", "step_ch", "yaw", "combo:yaw,z,pitch,roll"), ("Min langkah", "step_min", "0", 6),
                                  ("Toleransi", "step_tol", "0", 6), ("Tahan min (s)", "step_hold", "4", 5),
                                  ("Jendela maks (s)", "step_win", "30", 5)]),
    ("PWM-PPS", an_pwm, [("Ref PWM", "ref_pwm", "1700", 6), ("Stabil (s)", "settle", "2", 5)]),
    ("Jarak/Lintasan", an_dist, [("Jarak nyata (m)", "known", "0", 7)]),
]
