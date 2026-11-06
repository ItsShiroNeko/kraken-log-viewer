"""Gaya matplotlib dan pembuat Figure.

Memakai objek Figure langsung (bukan pyplot), jadi tidak perlu memilih backend:
mode laporan tanpa jendela dan mode GUI memakai kode yang sama.
"""
import matplotlib
from matplotlib.figure import Figure

matplotlib.rcParams.update({"font.size": 11, "axes.titlesize": 12, "axes.labelsize": 11, "xtick.labelsize": 10,
                            "ytick.labelsize": 10, "legend.fontsize": 10, "figure.dpi": 100})


def new_fig(h=7.0, w=12.0):
    return Figure(figsize=(w, h), dpi=100, constrained_layout=True)


def mark_cmds(ax, segs, label=False):
    for i, (c, a, b) in enumerate(segs):
        if i:
            ax.axvline(a, color="0.45", ls=":", lw=0.8)
        if label and len(segs) <= 18:
            ax.text(a, 0.98, " " + c, transform=ax.get_xaxis_transform(), rotation=90,
                    va="top", ha="right", fontsize=8, color="0.3")
