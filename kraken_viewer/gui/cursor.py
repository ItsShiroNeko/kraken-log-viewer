"""Kursor waktu + tirai di atas grafik matplotlib (blitting = mulus walau data besar)."""
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from ..utils import has


def time_axes(fig):
    """Sumbu yang x-nya = waktu log (berlabel 't [s]' atau berbagi sumbu x dengannya)."""
    base = [a for a in fig.axes if a.get_xlabel().startswith("t [s]")]
    out = []
    for a in fig.axes:
        if a in base:
            out.append(a)
            continue
        for b in base:
            try:
                if a.get_shared_x_axes().joined(a, b):
                    out.append(a)
                    break
            except Exception:
                pass
    return out


class Blit(object):
    """Menggambar ulang HANYA artis bergerak (kursor/tirai); grafik dasar tidak digambar ulang."""

    def __init__(self, canvas):
        self.canvas, self.fig = canvas, canvas.figure
        self.bg = None
        self.artists = []
        self.cids = [canvas.mpl_connect("draw_event", self._on_draw),
                     canvas.mpl_connect("resize_event", self._on_resize)]

    def add(self, a):
        a.set_animated(True)
        self.artists.append(a)

    def _on_resize(self, ev):
        self.bg = None

    def _on_draw(self, ev):
        self.bg = self.canvas.copy_from_bbox(self.fig.bbox)
        for a in self.artists:
            self.fig.draw_artist(a)

    def update(self):
        if self.bg is None:
            self.canvas.draw_idle()
            return
        self.canvas.restore_region(self.bg)
        for a in self.artists:
            self.fig.draw_artist(a)
        self.canvas.blit(self.fig.bbox)

    def close(self):
        for c in self.cids:
            try:
                self.canvas.mpl_disconnect(c)
            except Exception:
                pass


class TimeCursor(object):
    def __init__(self, canvas, fig, df, toolbar, on_click, curtain):
        self.canvas, self.toolbar, self.on_click = canvas, toolbar, on_click
        self.axes = time_axes(fig)
        self.blit = Blit(canvas)
        self.lines, self.curt, self.marker = [], [], None
        for ax in self.axes:
            ln = Line2D([0, 0], [0, 1], transform=ax.get_xaxis_transform(), color="#d62728", lw=1.6, zorder=10)
            ax.add_artist(ln)                      # add_artist: tidak mengubah batas sumbu
            self.blit.add(ln)
            self.lines.append(ln)
            rc = Rectangle((0, 0), 1e6, 1, transform=ax.get_xaxis_transform(), facecolor=(1, 1, 1, 0.9),
                           edgecolor="none", zorder=8)
            rc.set_visible(bool(curtain))
            ax.add_artist(rc)
            self.blit.add(rc)
            self.curt.append(rc)
        self.xy = None
        if has(df, "x", "y"):
            for ax in fig.axes:
                if ax.get_xlabel() == "X [m]" and ax.get_ylabel() == "Y [m]":
                    self.marker = Line2D([np.nan], [np.nan], marker="o", ms=11, mfc="#d62728", mec="k",
                                         ls="", zorder=11)
                    ax.add_artist(self.marker)
                    self.blit.add(self.marker)
                    self.xy = (df["t"].values, df["x"].values.astype(float), df["y"].values.astype(float))
                    break
        self.cid = canvas.mpl_connect("button_press_event", self._press)

    @property
    def usable(self):
        return bool(self.axes) or self.marker is not None

    def _press(self, ev):
        if ev.button != 1 or ev.xdata is None or ev.inaxes not in self.axes:
            return
        if self.toolbar is not None and str(getattr(self.toolbar, "mode", "")) != "":
            return                                  # sedang zoom/geser
        self.on_click(float(ev.xdata))

    def move(self, t):
        for ln in self.lines:
            ln.set_xdata([t, t])
        for rc in self.curt:
            rc.set_x(t)
        if self.marker is not None:
            tt, xx, yy = self.xy
            self.marker.set_data([np.interp(t, tt, xx)], [np.interp(t, tt, yy)])
        self.blit.update()

    def set_curtain(self, flag):
        for rc in self.curt:
            rc.set_visible(bool(flag))
        self.blit.update()

    def detach(self):
        try:
            self.canvas.mpl_disconnect(self.cid)
        except Exception:
            pass
        self.blit.close()
