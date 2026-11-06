"""Widget Tkinter: panel grafik yang bisa di-scroll dan kotak teks."""
import sys
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk


class FigurePane(ttk.Frame):
    """Toolbar + kanvas grafik (di-scroll bila grafik panjang)."""

    def __init__(self, master):
        ttk.Frame.__init__(self, master)
        self.bar = ttk.Frame(self)
        self.bar.pack(side="top", fill="x")
        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True)
        self.vsb = ttk.Scrollbar(body, orient="vertical")
        self.cv = tk.Canvas(body, highlightthickness=0, bg="white", yscrollcommand=self.vsb.set)
        self.vsb.configure(command=self.cv.yview)
        self.vsb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg="white")
        self.win = self.cv.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas = self.toolbar = self.fig = None
        self.h_in, self._job = 6.0, None
        self.cv.bind("<Configure>", lambda e: self._schedule_fit())
        top = self.winfo_toplevel()
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            top.bind(seq, self._wheel, add="+")

    def _wheel(self, ev):
        try:
            if not self.winfo_ismapped():
                return
            w = self.winfo_containing(ev.x_root, ev.y_root)
            while w is not None and w is not self:
                w = w.master
            if w is None:
                return
            if getattr(ev, "num", None) == 4:
                d = -1
            elif getattr(ev, "num", None) == 5:
                d = 1
            else:
                d = -int(ev.delta) if sys.platform == "darwin" else -int(ev.delta / 120)
            self.cv.yview_scroll(d * 3, "units")
        except tk.TclError:
            pass

    def clear(self):
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
            self.toolbar.destroy()
            self.canvas = self.toolbar = self.fig = None
        self.cv.configure(scrollregion=(0, 0, 1, 1))

    def show(self, fig):
        self.clear()
        self.fig = fig
        self.h_in = float(fig.get_size_inches()[1])
        self.canvas = FigureCanvasTkAgg(fig, master=self.inner)
        try:
            self.toolbar = NavigationToolbar2Tk(self.canvas, self.bar, pack_toolbar=False)
        except TypeError:                                   # matplotlib lama
            self.toolbar = NavigationToolbar2Tk(self.canvas, self.bar)
        self.toolbar.update()
        self.toolbar.pack(side="left")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.cv.yview_moveto(0)
        self._fit()
        return self.canvas

    def _schedule_fit(self):
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(120, self._fit)

    def _fit(self):
        self._job = None
        if self.fig is None:
            return
        wpx = max(self.cv.winfo_width(), 600)
        dpi = self.fig.dpi
        # grafik pendek mengisi area yang ada; grafik panjang (banyak panel) dibuat 70% tinggi aslinya lalu di-scroll
        hpx = max(int(self.h_in * dpi * 0.7), self.cv.winfo_height())
        self.fig.set_size_inches(wpx / dpi, hpx / dpi, forward=False)
        self.canvas.get_tk_widget().configure(width=wpx, height=hpx)
        self.cv.itemconfigure(self.win, width=wpx, height=hpx)
        self.cv.configure(scrollregion=(0, 0, wpx, hpx))
        self.canvas.draw_idle()


class TextBox(ttk.Frame):
    def __init__(self, master, font, height=10):
        ttk.Frame.__init__(self, master)
        self.txt = tk.Text(self, font=font, wrap="none", bg="#fbfbfd", relief="flat", padx=8, pady=6,
                           height=height, state="disabled")
        ys = ttk.Scrollbar(self, orient="vertical", command=self.txt.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.txt.xview)
        self.txt.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.txt.pack(side="left", fill="both", expand=True)

    def set(self, s):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", s)
        self.txt.configure(state="disabled")
