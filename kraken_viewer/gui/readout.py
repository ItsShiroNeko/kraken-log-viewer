"""Teks 'Nilai di waktu kursor' untuk panel kanan."""
import numpy as np

from ..analyses import TRACK_CH, pick_setpoint
from ..config import THR
from ..utils import has


class Readout(object):
    def __init__(self, data):
        df = data.df
        self.t = df["t"].values
        self.a = dict((c, df[c].values) for c in df.columns if c not in ("waktu", "cmd"))
        self.cmd = df["cmd"].values
        self.track = []
        for label, act, fw, gui, _tol, wrap, _unit in TRACK_CH:
            if has(df, act):
                self.track.append((label, act, pick_setpoint(df, fw, gui)[0], wrap))

    def _v(self, c, i):
        return float(self.a[c][i]) if c in self.a else float("nan")

    @staticmethod
    def _f(v, p=2, w=7):
        return "-".rjust(w) if v != v else ("%*.*f" % (w, p, v))

    def at(self, t):
        n = len(self.t)
        i = int(np.searchsorted(self.t, t))
        i = min(max(i, 0), n - 1)
        if i > 0 and abs(self.t[i - 1] - t) < abs(self.t[i] - t):
            i -= 1
        f, v = self._f, self._v
        L = ["t      %s s   (baris %d)" % (f(self.t[i], 2, 8), i + 1), "cmd    %s" % self.cmd[i], ""]
        if self.track:
            L.append("SIKAP (deg), NYELAM (cm)   aktual    sp      err")
            for label, act, sp, wrap in self.track:
                y = v(act, i)
                s = v(sp, i) if sp else float("nan")
                e = s - y
                if wrap and e == e:
                    e = (e + 180.0) % 360.0 - 180.0
                L.append("%-7s %s  %s  %s" % (label, f(y, 2, 9), f(s, 1, 7), f(e, 1, 7)))
            L.append("")
        if "gz" in self.a:
            L.append("gyro z  %s deg/s" % f(v("gz", i)))
        pps = [(k, v("pps_" + k, i)) for k in THR if "pps_" + k in self.a]
        if pps:
            L.append("PPS     " + "  ".join("%s %s" % (k.upper(), f(x, 1, 6)) for k, x in pps))
        pwm = [(k, v("pwm_" + k, i)) for k in THR if "pwm_" + k in self.a]
        if pwm:
            L.append("PWM     " + "  ".join("%s %s" % (k.upper(), f(x, 0, 5)) for k, x in pwm))
        if "x" in self.a and "y" in self.a:
            L.append("posisi  x %s  y %s m" % (f(v("x", i), 2, 6), f(v("y", i), 2, 6)))
        if "loop_us" in self.a:
            L.append("loop    %s us" % f(v("loop_us", i), 0, 6))
        return "\n".join(L)
