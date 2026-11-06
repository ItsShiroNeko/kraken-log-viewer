"""Jendela utama: tampilan sederhana + replay untuk log Kraken.

Cara pakai replay:
  * Tekan Putar: garis merah bergerak di semua grafik berbasis waktu, panel "Nilai di kursor"
    menampilkan roll/pitch/yaw, setpoint, error, PPS, PWM, perintah pada detik itu.
  * Klik langsung pada grafik = lompat ke waktu itu (otomatis jeda).
  * "Sembunyikan masa depan" = grafik tergambar bertahap seperti rekaman langsung.
  * "Tandai mulai/akhir" = jadikan waktu kursor sebagai batas rentang analisis, lalu seluruh
    angka (bias, RMS, drift, saran) dihitung ulang hanya untuk rentang itu.
  * Spasi = putar/jeda, panah kiri/kanan = mundur/maju 1 detik (Shift = 10 detik), Home = awal.
"""
import bisect
import os
import sys
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from ..analyses import TABS
from ..config import APP_TITLE, DEFAULT_LOG_DIR
from ..loader import cmd_segments, find_latest_log, load_log
from ..report import build_html, run_all
from ..utils import fnum
from .cursor import TimeCursor
from .readout import Readout
from .widgets import FigurePane, TextBox

SPEEDS = ["0.25x", "0.5x", "1x", "2x", "5x", "10x", "20x"]

DESC = {
    "Ringkasan": "Cek kualitas data lebih dulu: laju sampel, celah waktu, dan statistik tiap kolom.",
    "IMU": "Roll, pitch, yaw terhadap waktu, beserta drift dan noise.",
    "IMU Setpoint": "Aktual vs setpoint untuk yaw, pitch, roll, dan nyelam.",
    "Error Setpoint": "Seberapa jauh aktual dari setpoint (bias, RMS, % dalam toleransi) dan saran.",
    "PPS": "Putaran thruster (PPS) dan keseimbangan antar thruster.",
    "Perintah (CMD)": "Linimasa perintah GUI dan pengaruhnya ke yaw dan PPS.",
    "Analisis Statis": "Saat AUV diam: drift, noise, offset IMU. Pilih rentang diam lewat Tandai mulai/akhir.",
    "Respons Langkah": "Respons terhadap perubahan setpoint: overshoot, settle, saran gain. (Sumbu waktu = sejak langkah)",
    "PWM-PPS": "Hubungan PWM ke PPS dan saran trim thruster. (Butuh kolom pwm_*)",
    "Jarak/Lintasan": "Lintasan X-Y dan kalibrasi jarak per pulsa.",
}
EXTRA_CTRLS = {
    "IMU": [("Haluskan (titik)", "smooth", "1", 5)],
    "PPS": [("Haluskan (titik)", "smooth", "1", 5)],
}


class App(tk.Tk):
    def __init__(self, initial=None):
        tk.Tk.__init__(self, className="KrakenLogViewer")
        self.title(APP_TITLE)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry("%dx%d+%d+%d" % (int(sw * 0.96), int(sh * 0.90), int(sw * 0.02), int(sh * 0.03)))
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass
        for nm in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(nm).configure(size=10)
        fams = set(tkfont.families())
        self.mono = next((f for f in ("Consolas", "DejaVu Sans Mono", "Menlo", "Courier New") if f in fams), "TkFixedFont")
        self.fam = tkfont.nametofont("TkDefaultFont").actual("family")

        self.data = None
        self.readout = None
        self.cur = None
        self.current = None
        self.t = 0.0
        self.playing = False
        self._job = None
        self._last = 0.0
        self._last_readout = 0.0
        self._lock = False
        self.events = []

        self.analyses = []
        for name, fn, ctrls in TABS:
            self.analyses.append((name, fn, list(ctrls) + EXTRA_CTRLS.get(name, [])))
        self.by_name = dict((a[0], a) for a in self.analyses)
        self.vars = {"t0": tk.StringVar(value=""), "t1": tk.StringVar(value=""), "smooth": tk.StringVar(value="1")}
        for name, fn, ctrls in self.analyses:
            for label, key, default, spec in ctrls:
                if key not in self.vars:
                    self.vars[key] = tk.StringVar(value=default)
        self.speed_var = tk.StringVar(value="1x")
        self.curtain_var = tk.BooleanVar(value=False)
        self.loop_var = tk.BooleanVar(value=False)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._bind_keys()
        self.select(self.analyses[0][0])
        if initial:
            self.after(150, lambda: self.open_path(initial))

    # ------------------------------------------------------------------ susunan jendela
    def _btn(self, parent, text, fn, **kw):
        def run():
            fn()
            self.focus_set()                         # supaya Spasi tidak menekan tombol lagi
        return ttk.Button(parent, text=text, command=run, **kw)

    def _build(self):
        bold = (self.fam, 10, "bold")
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))
        mb = ttk.Menubutton(top, text="Buka log  \u25be")
        m = tk.Menu(mb, tearoff=0)
        m.add_command(label="Buka file CSV...", command=self.ask_file)
        m.add_command(label="Buka folder sesi...", command=self.ask_folder)
        mb["menu"] = m
        mb.pack(side="left")
        self._btn(top, "Log terbaru", self.open_latest).pack(side="left", padx=6)
        self.info = tk.StringVar(value="Belum ada log. Klik 'Buka log' atau 'Log terbaru'.")
        ttk.Label(top, textvariable=self.info).pack(side="left", padx=12)
        ex = ttk.Menubutton(top, text="Ekspor  \u25be")
        m2 = tk.Menu(ex, tearoff=0)
        m2.add_command(label="Laporan lengkap (HTML)...", command=self.export_html)
        m2.add_command(label="Semua gambar (PNG)...", command=self.export_png)
        ex["menu"] = m2
        ex.pack(side="right")

        # ---- bawah dulu (agar selalu terlihat): kontrol replay
        self._build_replay()

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8)
        side = ttk.Frame(body)
        side.pack(side="left", fill="y")
        ttk.Label(side, text="ANALISIS", font=bold).pack(anchor="w", pady=(0, 4))
        self.lb = tk.Listbox(side, exportselection=False, activestyle="none", width=17, font=(self.fam, 11),
                             relief="flat", highlightthickness=1, highlightbackground="#cfd6e4",
                             selectbackground="#0B3D91", selectforeground="white")
        for a in self.analyses:
            self.lb.insert("end", "  " + a[0])
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", self._on_pick)

        pw = ttk.PanedWindow(body, orient="horizontal")
        pw.pack(side="left", fill="both", expand=True, padx=(8, 0))
        center = ttk.Frame(pw)
        pw.add(center, weight=5)
        right = ttk.PanedWindow(pw, orient="vertical")
        pw.add(right, weight=2)

        self.title_var = tk.StringVar()
        self.desc_var = tk.StringVar()
        self.hint_var = tk.StringVar()
        ttk.Label(center, textvariable=self.title_var, font=(self.fam, 14, "bold")).pack(anchor="w")
        ttk.Label(center, textvariable=self.desc_var, foreground="#555").pack(anchor="w")
        self.opt = ttk.Frame(center)
        self.opt.pack(fill="x", pady=(4, 2))
        tk.Label(center, textvariable=self.hint_var, fg="#b35900", anchor="w").pack(fill="x")
        self.pane = FigurePane(center)
        self.pane.pack(fill="both", expand=True)

        lf1 = ttk.LabelFrame(right, text="Nilai di waktu kursor")
        self.read_box = TextBox(lf1, (self.mono, 10), height=13)
        self.read_box.pack(fill="both", expand=True)
        lf2 = ttk.LabelFrame(right, text="Hasil analisis")
        self.res_box = TextBox(lf2, (self.mono, 10), height=10)
        self.res_box.pack(fill="both", expand=True)
        right.add(lf1, weight=2)
        right.add(lf2, weight=3)

    def _build_replay(self):
        bar = ttk.LabelFrame(self, text="Replay")
        bar.pack(side="bottom", fill="x", padx=8, pady=6)
        r1 = ttk.Frame(bar)
        r1.pack(fill="x", padx=6, pady=(4, 2))
        self._btn(r1, "|<  Awal", self.to_start, width=9).pack(side="left")
        self.play_btn = ttk.Button(r1, text="\u25b6  Putar", width=10, command=lambda: (self.toggle(), self.focus_set()))
        self.play_btn.pack(side="left", padx=4)
        ttk.Label(r1, text="Kecepatan").pack(side="left", padx=(8, 2))
        cb = ttk.Combobox(r1, textvariable=self.speed_var, values=SPEEDS, width=6, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.focus_set())
        self.scale = ttk.Scale(r1, orient="horizontal", from_=0.0, to=1.0, command=self._on_scale)
        self.scale.pack(side="left", fill="x", expand=True, padx=10)
        self.time_var = tk.StringVar(value="0.00 / 0.00 s")
        ttk.Label(r1, textvariable=self.time_var, font=(self.mono, 11, "bold"), width=18).pack(side="left")

        r2 = ttk.Frame(bar)
        r2.pack(fill="x", padx=6, pady=(2, 2))
        ttk.Checkbutton(r2, text="Sembunyikan masa depan", variable=self.curtain_var,
                        command=self._on_curtain).pack(side="left")
        ttk.Checkbutton(r2, text="Ulangi", variable=self.loop_var).pack(side="left", padx=8)
        ttk.Label(r2, text="Lompat ke kejadian:").pack(side="left", padx=(14, 2))
        self._btn(r2, "<", self.prev_event, width=2).pack(side="left")
        self.jump = ttk.Combobox(r2, values=[], width=24, state="readonly")
        self.jump.pack(side="left", padx=2)
        self.jump.bind("<<ComboboxSelected>>", self._on_jump)
        self._btn(r2, ">", self.next_event, width=2).pack(side="left")
        self._btn(r2, "Tandai mulai", self.mark_start).pack(side="left", padx=(16, 2))
        self._btn(r2, "Tandai akhir", self.mark_end).pack(side="left", padx=2)
        self._btn(r2, "Reset rentang", self.reset_range).pack(side="left", padx=2)
        self.range_var = tk.StringVar(value="Rentang analisis: seluruh log")
        ttk.Label(r2, textvariable=self.range_var).pack(side="left", padx=8)
        ttk.Label(bar, text="Klik grafik = lompat ke waktu itu   |   Spasi = putar/jeda   |   \u2190/\u2192 = \u00b11 dtk "
                            "(Shift \u00b110 dtk)   |   Home = awal", foreground="#666").pack(anchor="w", padx=8, pady=(0, 4))

    def _bind_keys(self):
        def guarded(fn):
            def h(ev):
                if isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
                    return None
                fn()
                return "break"
            return h
        self.bind_all("<space>", guarded(self.toggle))
        self.bind_all("<Left>", guarded(lambda: self.nudge(-1)))
        self.bind_all("<Right>", guarded(lambda: self.nudge(1)))
        self.bind_all("<Shift-Left>", guarded(lambda: self.nudge(-10)))
        self.bind_all("<Shift-Right>", guarded(lambda: self.nudge(10)))
        self.bind_all("<Home>", guarded(self.to_start))

    # ------------------------------------------------------------------ pilih analisis
    def _on_pick(self, ev=None):
        sel = self.lb.curselection()
        if sel:
            self.select(self.analyses[sel[0]][0])
            self.focus_set()

    def select(self, name):
        self.current = name
        idx = [a[0] for a in self.analyses].index(name)
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(idx)
        _, _, ctrls = self.by_name[name]
        self.title_var.set(name)
        self.desc_var.set(DESC.get(name, ""))
        for w in self.opt.winfo_children():
            w.destroy()
        for label, key, default, spec in ctrls:
            ttk.Label(self.opt, text=label).pack(side="left", padx=(0, 2))
            if isinstance(spec, str) and spec.startswith("combo:"):
                c = ttk.Combobox(self.opt, textvariable=self.vars[key], values=spec[6:].split(","), width=9, state="readonly")
                c.pack(side="left", padx=(0, 10))
                c.bind("<<ComboboxSelected>>", lambda e: (self.render(), self.focus_set()))
            else:
                e = ttk.Entry(self.opt, textvariable=self.vars[key], width=spec)
                e.pack(side="left", padx=(0, 10))
                e.bind("<Return>", lambda ev: self.render())
        if ctrls:
            self._btn(self.opt, "Terapkan", self.render).pack(side="left")
        self.render()

    # ------------------------------------------------------------------ render
    def opts(self):
        return dict((k, v.get()) for k, v in self.vars.items())

    def render(self):
        if self.current is None:
            return
        if self.cur is not None:
            self.cur.detach()
            self.cur = None
        self.hint_var.set("")
        if self.data is None:
            self.pane.clear()
            self.res_box.set("Belum ada data. Buka file log lebih dulu.")
            self.read_box.set("")
            return
        fn = self.by_name[self.current][1]
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            fig, text = fn(self.data, self.opts())
        except Exception:
            fig, text = None, "Gagal menganalisis:\n" + traceback.format_exc()
        self.config(cursor="")
        self.res_box.set(text)
        if fig is None:
            self.pane.clear()
            self.hint_var.set("Tidak ada grafik untuk pengaturan ini. Baca penjelasan di panel 'Hasil analisis'.")
        else:
            canvas = self.pane.show(fig)
            self.cur = TimeCursor(canvas, fig, self.data.df, self.pane.toolbar, self.on_graph_click,
                                  self.curtain_var.get())
            if not self.cur.usable:
                self.hint_var.set("Grafik ini tidak berbasis waktu log, jadi garis kursor tidak tampil. "
                                  "Panel 'Nilai di waktu kursor' tetap mengikuti replay.")
        self.set_time(self.t)

    # ------------------------------------------------------------------ data
    def ask_file(self):
        init = DEFAULT_LOG_DIR if os.path.isdir(DEFAULT_LOG_DIR) else os.path.expanduser("~")
        p = filedialog.askopenfilename(title="Pilih telemetry CSV", initialdir=init,
                                       filetypes=[("CSV", "*.csv"), ("Semua", "*.*")])
        if p:
            self.open_path(p)

    def ask_folder(self):
        init = DEFAULT_LOG_DIR if os.path.isdir(DEFAULT_LOG_DIR) else os.path.expanduser("~")
        p = filedialog.askdirectory(title="Pilih folder sesi log", initialdir=init)
        if p:
            self.open_path(p)

    def open_latest(self):
        p = find_latest_log()
        if not p:
            messagebox.showinfo(APP_TITLE, "Tidak ada log di:\n" + DEFAULT_LOG_DIR)
            return
        self.open_path(p)

    def open_path(self, path):
        self.pause()
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            data = load_log(path)
        except Exception as e:
            self.config(cursor="")
            messagebox.showerror(APP_TITLE, "Gagal membuka log:\n%s" % e)
            return
        self.config(cursor="")
        self.data = data
        self.readout = Readout(data)
        self.vars["t0"].set("")
        self.vars["t1"].set("")
        self.info.set("%s  |  %d baris  |  %.1f s  |  waktu: %s" % (data.name, len(data.df), data.duration, data.timebase))
        self.title("%s - %s" % (APP_TITLE, data.name))
        segs = cmd_segments(data.df)
        self.events = [(a, c) for c, a, b in segs]
        self.jump["values"] = ["%7.1f s   %s" % (a, c) for a, c in self.events]
        self.jump.set("")
        self.t = 0.0
        self._range_changed(rerender=False)
        self.render()

    # ------------------------------------------------------------------ rentang & waktu
    def lohi(self):
        d = self.data.duration if self.data is not None else 1.0
        o = self.opts()
        lo, hi = fnum(o, "t0", None), fnum(o, "t1", None)
        lo = 0.0 if lo is None else max(0.0, lo)
        hi = d if hi is None else min(d, hi)
        if hi <= lo:
            lo, hi = 0.0, d
        return lo, hi

    def _range_changed(self, rerender=True):
        lo, hi = self.lohi()
        self.scale.configure(from_=lo, to=hi if hi > lo else lo + 1.0)
        if self.vars["t0"].get().strip() == "" and self.vars["t1"].get().strip() == "":
            self.range_var.set("Rentang analisis: seluruh log")
        else:
            self.range_var.set("Rentang analisis: %.1f - %.1f s" % (lo, hi))
        self.t = min(max(self.t, lo), hi)
        if rerender:
            self.render()

    def mark_start(self):
        if self.data is None:
            return
        _, hi = self.lohi()
        if self.t >= hi - 0.05:
            messagebox.showinfo(APP_TITLE, "Waktu mulai harus lebih awal dari akhir rentang.")
            return
        self.vars["t0"].set("%.2f" % self.t)
        self._range_changed()

    def mark_end(self):
        if self.data is None:
            return
        lo, _ = self.lohi()
        if self.t <= lo + 0.05:
            messagebox.showinfo(APP_TITLE, "Waktu akhir harus lebih lambat dari awal rentang.")
            return
        self.vars["t1"].set("%.2f" % self.t)
        self._range_changed()

    def reset_range(self):
        self.vars["t0"].set("")
        self.vars["t1"].set("")
        self._range_changed()

    def set_time(self, t, update_text=True):
        lo, hi = self.lohi()
        self.t = min(max(t, lo), hi)
        self._lock = True
        try:
            self.scale.set(self.t)
        finally:
            self._lock = False
        self.time_var.set("%.2f / %.2f s" % (self.t, hi))
        if self.cur is not None:
            self.cur.move(self.t)
        if update_text:
            self.update_readout()

    def update_readout(self):
        self._last_readout = time.monotonic()
        if self.readout is not None:
            self.read_box.set(self.readout.at(self.t))

    def _on_scale(self, val):
        if self._lock or self.data is None:
            return
        self.set_time(float(val))

    def _on_curtain(self):
        if self.cur is not None:
            self.cur.set_curtain(self.curtain_var.get())
        self.focus_set()

    def on_graph_click(self, t):
        self.pause()
        self.set_time(t)

    # ------------------------------------------------------------------ kejadian (perintah)
    def _on_jump(self, ev=None):
        i = self.jump.current()
        if 0 <= i < len(self.events):
            self.pause()
            self.set_time(self.events[i][0])
        self.focus_set()

    def prev_event(self):
        starts = [a for a, c in self.events]
        i = bisect.bisect_left(starts, self.t - 0.05) - 1
        if i >= 0:
            self.pause()
            self.set_time(starts[i])
            self.jump.current(i)

    def next_event(self):
        starts = [a for a, c in self.events]
        i = bisect.bisect_right(starts, self.t + 0.05)
        if i < len(starts):
            self.pause()
            self.set_time(starts[i])
            self.jump.current(i)

    # ------------------------------------------------------------------ pemutaran
    def speed(self):
        try:
            return float(self.speed_var.get().rstrip("x"))
        except ValueError:
            return 1.0

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if self.data is None:
            return
        lo, hi = self.lohi()
        if self.t >= hi - 0.01:
            self.set_time(lo)
        self.playing = True
        self.play_btn.config(text="||  Jeda")
        self._last = time.monotonic()
        self._tick()

    def pause(self):
        self.playing = False
        self.play_btn.config(text="\u25b6  Putar")
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _tick(self):
        if not self.playing:
            return
        now = time.monotonic()
        dt, self._last = now - self._last, now
        lo, hi = self.lohi()
        t = self.t + dt * self.speed()
        if t >= hi:
            if self.loop_var.get():
                t = lo
            else:
                self.set_time(hi)
                self.pause()
                return
        self.set_time(t, update_text=(now - self._last_readout) > 0.1)
        self._job = self.after(30, self._tick)

    def to_start(self):
        lo, _ = self.lohi()
        self.set_time(lo)

    def nudge(self, sec):
        self.set_time(self.t + sec)

    # ------------------------------------------------------------------ ekspor
    def _results(self):
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            return run_all(self.data, self.opts())
        finally:
            self.config(cursor="")

    def export_html(self):
        if self.data is None:
            messagebox.showinfo(APP_TITLE, "Buka file log dulu.")
            return
        p = filedialog.asksaveasfilename(title="Simpan laporan", initialdir=os.path.dirname(self.data.files[0]),
                                         defaultextension=".html", initialfile="laporan_%s.html" % self.data.name,
                                         filetypes=[("HTML", "*.html")])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(build_html(self.data, self.opts(), self._results()))
        except Exception as e:
            messagebox.showerror(APP_TITLE, "Gagal menyimpan:\n%s" % e)
            return
        messagebox.showinfo(APP_TITLE, "Laporan tersimpan:\n" + p)

    def export_png(self):
        if self.data is None:
            messagebox.showinfo(APP_TITLE, "Buka file log dulu.")
            return
        d = filedialog.askdirectory(title="Folder tujuan gambar", initialdir=os.path.dirname(self.data.files[0]))
        if not d:
            return
        n, txt = 0, []
        for i, (name, fig, text) in enumerate(self._results(), 1):
            safe = "".join(ch if ch.isalnum() else "_" for ch in name)
            if fig is not None:
                fig.savefig(os.path.join(d, "%02d_%s.png" % (i, safe)), dpi=130)
                n += 1
            txt.append("=== %s ===\n%s\n" % (name, text))
        with open(os.path.join(d, "ringkasan.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(txt))
        messagebox.showinfo(APP_TITLE, "%d gambar + ringkasan.txt tersimpan di:\n%s" % (n, d))

    def on_close(self):
        self.pause()
        self.destroy()


def run_gui(initial=None, hard_exit=True):
    """Buka jendela. hard_exit=True menutup proses langsung setelah jendela ditutup
    (menghindari proses menggantung akibat thread Tk/matplotlib)."""
    if sys.platform == "win32":                       # tampilan tajam di layar DPI tinggi
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    try:
        app = App(initial)
    except tk.TclError as e:
        sys.exit("Tidak bisa membuka jendela (tidak ada layar grafis?): %s\n"
                 "Untuk laporan tanpa jendela:  kraken-viewer <log> --report laporan.html" % e)
    app.mainloop()
    if hard_exit:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
