"""Interface desktop moderna (Tkinter) para a impressora X8-04A1."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from PIL import Image, ImageTk

from . import jbig, protocol, render
from .transport import DEFAULT_MAC, Printer, PrinterError

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:  # sem tkinterdnd2: segue sem arrastar-e-soltar
    DND_FILES = None
    BaseTk = tk.Tk
    HAS_DND = False

DPI = 8  # dots por mm (203 dpi)
PAGE_SIZES = {
    "A4 · 210 × 297 mm": (210, 297),
    "A5 · 148 × 210 mm": (148, 210),
    "Letter · 216 × 279 mm": (216, 279),
}
MAX_WIDTH = 1728

# Paleta (Catppuccin Mocha)
BG = "#11111b"
CARD = "#1e1e2e"
CARD2 = "#181825"
FG = "#cdd6f4"
MUTED = "#a6adc8"
ACCENT = "#89b4fa"
ACCENT_HOVER = "#b4befe"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"
BORDER = "#313244"
TRACK = "#45475a"


class Switch(tk.Canvas):
    """Switch no estilo iOS, desenhado em canvas."""

    def __init__(self, parent: tk.Misc, variable: tk.BooleanVar,
                 bg: str = CARD) -> None:
        super().__init__(parent, width=42, height=22, bg=bg,
                         highlightthickness=0, cursor="hand2")
        self.var = variable
        self.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _toggle(self, _event=None) -> None:
        self.var.set(not self.var.get())

    def _draw(self) -> None:
        self.delete("all")
        on = self.var.get()
        color = ACCENT if on else TRACK
        self.create_oval(2, 2, 20, 20, fill=color, outline=color)
        self.create_oval(22, 2, 40, 20, fill=color, outline=color)
        self.create_rectangle(11, 2, 31, 20, fill=color, outline=color)
        x = 24 if on else 4
        self.create_oval(x, 4, x + 14, 18, fill="white", outline="white")


class Slider(tk.Canvas):
    """Slider moderno desenhado em canvas."""

    def __init__(self, parent: tk.Misc, variable: tk.IntVar,
                 low: int = 5, high: int = 60, bg: str = CARD,
                 accent: str = ACCENT, command=None) -> None:
        super().__init__(parent, height=26, bg=bg, highlightthickness=0,
                         cursor="hand2")
        self.var = variable
        self.low = low
        self.high = high
        self.accent = accent
        self.command = command
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._from_event)
        self.bind("<B1-Motion>", self._from_event)
        self.var.trace_add("write", lambda *_: self._draw())

    def _from_event(self, event) -> None:
        width = max(1, self.winfo_width())
        pad = 10
        ratio = (event.x - pad) / max(1, width - 2 * pad)
        ratio = max(0.0, min(1.0, ratio))
        value = round(self.low + ratio * (self.high - self.low))
        self.var.set(value)
        if self.command:
            self.command(value)

    def _draw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        pad = 10
        y = 13
        self.create_line(pad, y, width - pad, y, fill=TRACK, width=4,
                         capstyle="round")
        ratio = (self.var.get() - self.low) / (self.high - self.low)
        x = pad + ratio * (width - 2 * pad)
        self.create_line(pad, y, x, y, fill=self.accent, width=4,
                         capstyle="round")
        self.create_oval(x - 7, y - 7, x + 7, y + 7, fill=self.accent,
                         outline=BG, width=2)


class App(BaseTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("X8-04A1 — Impressora térmica")
        self.geometry("1280x920")
        self.minsize(1060, 720)
        self.configure(bg=BG)

        families = set(tkfont.families())
        self.font = next((f for f in ("Inter", "Ubuntu", "Noto Sans",
                                      "DejaVu Sans") if f in families),
                         "TkDefaultFont")
        self.mono = next((f for f in ("JetBrains Mono", "Ubuntu Mono",
                                      "DejaVu Sans Mono") if f in families),
                         "TkFixedFont")

        self.page_w = 0
        self.page_h = 0
        self.scale = 1.0
        self.origin = (0.0, 0.0)
        self.page_image = Image.new("L", (1, 1), 255)
        self.photo = None
        self.selection: tuple[int, int, int, int] | None = None
        self.drag_start: tuple[int, int] | None = None
        self.drag_rect: int | None = None
        self.drag_mode: str | None = None
        self.resize_edge: str | None = None
        self.selection_origin: tuple[int, int, int, int] | None = None
        self.selected_placement: int | None = None
        self.placement_drag_mode: str | None = None
        self.placement_edge: str | None = None
        self.placement_origin: dict | None = None
        self.placement_start: tuple[int, int] | None = None
        self._base_cache: dict[int, Image.Image] = {}
        self.page_selections: dict[int, tuple[int, int, int, int]] = {}
        self.busy = False

        self.pages: list[dict] = []
        self.current_page = 0
        self._page_cache: dict[int, Image.Image] = {}
        self.page_index = tk.IntVar(value=1)
        self.page_total = tk.StringVar(value="de 1")

        self.status = tk.StringVar(value="pronta")
        self.device = tk.StringVar(value=DEFAULT_MAC)
        self.devices: dict[str, str] = {}
        self._density_buttons: dict[int, tk.Button] = {}
        self.apply_all = tk.BooleanVar(value=False)

        self._build_ui()
        self.apply_all.trace_add("write", lambda *_: self._on_apply_all())
        self._new_page("A4 · 210 × 297 mm")
        self.after(200, self.redraw)
        self.after(300, self.refresh_devices_async)

    # -------------------------------------------------------------- estilo
    def _button(self, parent: tk.Misc, text: str, command,
                *, bg: str = CARD2, fg: str = FG, hover: str = TRACK,
                size: int = 10, bold: bool = False, pady: int = 8) -> tk.Button:
        button = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg, relief="flat",
            bd=0, highlightthickness=0, cursor="hand2", padx=10, pady=pady,
            font=(self.font, size, "bold" if bold else "normal"))
        button._base_bg = bg
        button._hover_bg = hover
        button.bind("<Enter>", lambda _e: button.configure(bg=hover)
                    if str(button["state"]) != "disabled" else None)
        button.bind("<Leave>", lambda _e: button.configure(
            bg=button._base_bg) if str(button["state"]) != "disabled" else None)
        return button

    def _section(self, parent: tk.Misc, title: str) -> None:
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=18,
                                                   pady=(16, 0))
        tk.Label(parent, text=title.upper(), bg=CARD, fg=MUTED,
                 font=(self.font, 8, "bold")).pack(anchor="w", padx=18,
                                                   pady=(10, 6))

    def _toggle_row(self, parent: tk.Misc, text: str,
                    variable: tk.BooleanVar) -> None:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=18, pady=3)
        tk.Label(row, text=text, bg=CARD, fg=FG,
                 font=(self.font, 10)).pack(side="left")
        Switch(row, variable, CARD).pack(side="right")

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TCombobox", fieldbackground=CARD2, background=CARD2,
            foreground=FG, arrowcolor=MUTED, bordercolor=BORDER,
            lightcolor=CARD2, darkcolor=CARD2, padding=6)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", CARD2)],
            foreground=[("readonly", FG)],
            background=[("readonly", CARD2)],
            selectbackground=[("readonly", CARD2)],
            selectforeground=[("readonly", FG)])
        style.configure("Vertical.TScrollbar", background=CARD,
                        troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)

        self.option_add("*TCombobox*Listbox.background", CARD2)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.option_add("*TCombobox*Listbox.font", (self.font, 10))

        # header ---------------------------------------------------------
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(16, 10))
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left")
        tk.Label(brand, text="X8", bg=BG, fg=ACCENT,
                 font=(self.font, 26, "bold")).pack(side="left")
        tk.Label(brand, text="  impressora térmica", bg=BG, fg=MUTED,
                 font=(self.font, 11)).pack(side="left", pady=(8, 0))

        state = tk.Frame(header, bg=BG)
        state.pack(side="right")
        dot = tk.Canvas(state, width=10, height=10, bg=BG,
                        highlightthickness=0)
        dot.create_oval(1, 1, 9, 9, fill=GREEN, outline="")
        dot.pack(side="left", padx=(0, 8))
        tk.Label(state, textvariable=self.status, bg=BG, fg=MUTED,
                 font=(self.font, 10), anchor="e").pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        # preview --------------------------------------------------------
        preview = tk.Frame(body, bg=CARD2, highlightbackground=BORDER,
                           highlightthickness=1)
        preview.pack(side="left", fill="both", expand=True)
        tk.Label(preview, text="Arraste imagens para a página · alças "
                               "vermelhas = área · Delete remove imagem",
                 bg=CARD2, fg=MUTED, font=(self.font, 9)).pack(
            side="bottom", pady=9)
        self.canvas = tk.Canvas(preview, bg=CARD2, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())
        if HAS_DND:
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind("<<Drop>>", self._on_drop)
        self.bind("<Delete>", self._delete_placement)

        # sidebar --------------------------------------------------------
        outer = tk.Frame(body, bg=BG, width=386)
        outer.pack(side="right", fill="y", padx=(16, 0))
        outer.pack_propagate(False)

        footer = tk.Frame(outer, bg=CARD, highlightbackground=BORDER,
                          highlightthickness=1)
        footer.pack(side="bottom", fill="x", padx=(0, 14))
        self.print_btn = self._button(
            footer, "IMPRIMIR PÁGINA", self.print_job, bg=ACCENT, fg=BG,
            hover=ACCENT_HOVER, size=11, bold=True, pady=10)
        self.print_btn.pack(fill="x", padx=12, pady=(12, 6))
        actions = tk.Frame(footer, bg=CARD)
        actions.pack(fill="x", padx=12, pady=(0, 12))
        self._button(actions, "Todas", self.print_all,
                     pady=5).pack(side="left", expand=True, fill="x",
                                  padx=(0, 4))
        self._button(actions, "Salvar job", self.save_job,
                     pady=5).pack(side="left", expand=True, fill="x",
                                  padx=(0, 4))
        self._button(actions, "Status", self.query_status,
                     pady=5).pack(side="left", expand=True, fill="x")

        content = tk.Frame(outer, bg=BG)
        content.pack(side="top", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(content, orient="vertical",
                                  style="Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        side_canvas = tk.Canvas(content, bg=BG, highlightthickness=0,
                                width=370, yscrollcommand=scrollbar.set)
        side_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=side_canvas.yview)
        self.side_canvas = side_canvas
        side = tk.Frame(side_canvas, bg=CARD)
        side_canvas.create_window((0, 0), window=side, anchor="nw",
                                  width=368)
        side.bind("<Configure>", lambda _e: side_canvas.configure(
            scrollregion=side_canvas.bbox("all")))
        for seq in ("<Button-4>", "<Button-5>"):
            side_canvas.bind_all(
                seq, lambda e: side_canvas.yview_scroll(
                    -1 if e.num == 4 else 1, "units"))
        side_canvas.bind_all(
            "<MouseWheel>",
            lambda e: side_canvas.yview_scroll(int(-e.delta / 120), "units"))

        # dispositivo (topo, sempre visivel)
        tk.Label(side, text="IMPRESSORA BLUETOOTH", bg=CARD, fg=MUTED,
                 font=(self.font, 8, "bold")).pack(anchor="w", padx=18,
                                                   pady=(16, 6))
        self.device_cb = ttk.Combobox(side, textvariable=self.device,
                                      values=[])
        self.device_cb.pack(fill="x", padx=18)
        device_row = tk.Frame(side, bg=CARD)
        device_row.pack(fill="x", padx=18, pady=(6, 2))
        self._button(device_row, "Atualizar",
                     self.refresh_devices_async, pady=5).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        self._button(device_row, "Escanear",
                     self.scan_devices_async, pady=5).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self.after(50, lambda: self.side_canvas.yview_moveto(0))

        # conteudo
        self._section(side, "Conteúdo")
        row = tk.Frame(side, bg=CARD)
        row.pack(fill="x", padx=18)
        for index, (label, callback) in enumerate(
                (("Imagem", self.open_image), ("PDF", self.open_pdf),
                 ("Texto", self.open_text))):
            button = self._button(row, label, callback)
            button.pack(side="left", expand=True, fill="x",
                        padx=(0 if index == 0 else 5, 0))

        pdf_row = tk.Frame(side, bg=CARD)
        pdf_row.pack(fill="x", padx=18, pady=(8, 0))
        tk.Label(pdf_row, text="PDF", bg=CARD, fg=MUTED,
                 font=(self.font, 9)).pack(side="left")
        self._button(pdf_row, "Recarregar página", self.reload_pdf,
                     pady=4).pack(side="right")

        # paginas
        self._section(side, "Páginas")
        nav = tk.Frame(side, bg=CARD)
        nav.pack(fill="x", padx=18)
        self._button(nav, "‹", lambda: self.goto_page(self.current_page - 1),
                     size=13, pady=2).pack(side="left")
        self.page_spin = tk.Spinbox(
            nav, from_=1, to=1, width=4, textvariable=self.page_index,
            command=self._goto_spin, bg=CARD2, fg=FG, bd=0, relief="flat",
            buttonbackground=CARD2, highlightthickness=1,
            highlightbackground=BORDER, insertbackground=FG,
            font=(self.font, 10))
        self.page_spin.pack(side="left", padx=6)
        tk.Label(nav, textvariable=self.page_total, bg=CARD, fg=MUTED,
                 font=(self.font, 10)).pack(side="left")
        self._button(nav, "›", lambda: self.goto_page(self.current_page + 1),
                     size=13, pady=2).pack(side="right")

        # pagina
        self._section(side, "Página")
        self.page_size = tk.StringVar(value="A4 · 210 × 297 mm")
        page_cb = ttk.Combobox(side, textvariable=self.page_size,
                               values=list(PAGE_SIZES), state="readonly")
        page_cb.pack(fill="x", padx=18)
        page_cb.bind("<<ComboboxSelected>>", self._on_page_size)

        # area
        self._section(side, "Área de impressão")
        self.sel_label = tk.Label(side, text="arraste no papel",
                                  bg=CARD, fg=FG,
                                  font=(self.mono, 10))
        self.sel_label.pack(anchor="w", padx=18)
        self._button(side, "Selecionar página inteira",
                     self.select_all).pack(fill="x", padx=18, pady=(8, 0))
        apply_row = tk.Frame(side, bg=CARD)
        apply_row.pack(fill="x", padx=18, pady=(4, 0))
        tk.Label(apply_row, text="Aplicar a todas as páginas", bg=CARD,
                 fg=FG, font=(self.font, 10)).pack(side="left")
        Switch(apply_row, self.apply_all, CARD).pack(side="right")

        # qualidade
        self._section(side, "Qualidade")
        self.density = tk.IntVar(value=2)
        segment = tk.Frame(side, bg=CARD2, highlightbackground=BORDER,
                           highlightthickness=1)
        segment.pack(fill="x", padx=18)
        for value, label in ((1, "Clara"), (2, "Normal"), (3, "Escura")):
            button = tk.Button(
                segment, text=label, command=lambda v=value: self._set_density(v),
                relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                font=(self.font, 9), pady=6)
            button.pack(side="left", expand=True, fill="x")
            self._density_buttons[value] = button
        self._update_density()

        speed_row = tk.Frame(side, bg=CARD)
        speed_row.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(speed_row, text="Velocidade", bg=CARD, fg=FG,
                 font=(self.font, 9)).pack(side="left")
        self.speed = tk.IntVar(value=30)
        self.speed_label = tk.Label(speed_row, text="30", bg=CARD, fg=MUTED,
                                    font=(self.mono, 9))
        self.speed_label.pack(side="right")
        Slider(side, self.speed, 5, 60, CARD,
               command=lambda v: self.speed_label.configure(
                   text=str(v))).pack(fill="x", padx=14)

        algo_row = tk.Frame(side, bg=CARD)
        algo_row.pack(fill="x", padx=18, pady=(4, 0))
        tk.Label(algo_row, text="Algoritmo", bg=CARD, fg=FG,
                 font=(self.font, 9)).pack(side="left")
        self.algorithm = tk.IntVar(value=1)
        ttk.Combobox(algo_row, textvariable=self.algorithm, values=(1, 2),
                     width=4, state="readonly").pack(side="right")

        # opcoes
        self._section(side, "Opções")
        self.keep_position = tk.BooleanVar(value=True)
        self._toggle_row(side, "Manter posição na folha",
                         self.keep_position)
        self.eject = tk.BooleanVar(value=False)
        self._toggle_row(side, "Ejetar a folha ao terminar", self.eject)

        # papel
        self._section(side, "Papel")
        paper_row = tk.Frame(side, bg=CARD)
        paper_row.pack(fill="x", padx=18, pady=(0, 2))
        self.feed_mm = tk.IntVar(value=10)
        tk.Spinbox(paper_row, from_=1, to=280, width=5,
                   textvariable=self.feed_mm, bg=CARD2, fg=FG, bd=0,
                   relief="flat", buttonbackground=CARD2,
                   highlightthickness=1, highlightbackground=BORDER,
                   insertbackground=FG, font=(self.font, 9)).pack(side="left")
        self._button(paper_row, "Avançar (mm)", self.feed,
                     pady=5).pack(side="right")

    # ------------------------------------------------------------- página
    def _new_page(self, label: str) -> None:
        mm_w, mm_h = PAGE_SIZES.get(label, PAGE_SIZES["A4 · 210 × 297 mm"])
        self.page_w = mm_w * DPI
        self.page_h = mm_h * DPI
        self.page_image = Image.new("L", (self.page_w, self.page_h), 255)
        self.selection = (0, 0, self.page_w, self.page_h)
        self.page_selections = {
            index: self.selection for index in range(len(self.pages))}
        self._page_cache.clear()
        self._base_cache.clear()
        self.selected_placement = None
        if self.pages:
            self._show_page(self.current_page)
        else:
            self.redraw()

    def _on_page_size(self, _event=None) -> None:
        self._new_page(self.page_size.get())

    def _page_geometry(self) -> None:
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        margin = 28
        self.scale = min((cw - 2 * margin) / self.page_w,
                         (ch - 2 * margin) / self.page_h)
        w = self.page_w * self.scale
        h = self.page_h * self.scale
        self.origin = ((cw - w) / 2, (ch - h) / 2)

    def redraw(self) -> None:
        if not self.page_w:
            return
        self._page_geometry()
        self.canvas.delete("all")
        ox, oy = self.origin
        w = self.page_w * self.scale
        h = self.page_h * self.scale

        self.canvas.create_rectangle(ox + 5, oy + 5, ox + w + 5, oy + h + 5,
                                     fill="#0a0a12", outline="")
        self.canvas.create_rectangle(ox, oy, ox + w, oy + h, fill="white",
                                     outline=BORDER)

        if self.page_image.size != (1, 1):
            disp = self.page_image.resize(
                (max(1, int(w)), max(1, int(h))), Image.LANCZOS)
            self.photo = ImageTk.PhotoImage(disp)
            self.canvas.create_image(ox, oy, image=self.photo, anchor="nw")

        if self.selection:
            self._draw_selection()
        else:
            self._update_sel_label()
        self._draw_placement_selection()

    # ------------------------------------------------------------ seleção
    def _selection_canvas(self) -> tuple[float, float, float, float]:
        ox, oy = self.origin
        x0, y0, x1, y1 = self.selection
        return (ox + x0 * self.scale, oy + y0 * self.scale,
                ox + x1 * self.scale, oy + y1 * self.scale)

    @staticmethod
    def _handle_at(x: float, y: float, rect) -> str | None:
        cx0, cy0, cx1, cy1 = rect
        xs = (cx0, (cx0 + cx1) / 2, cx1)
        ys = (cy0, (cy0 + cy1) / 2, cy1)
        names = (("nw", "n", "ne"), ("w", None, "e"), ("sw", "s", "se"))
        tolerance = 8
        for row, py in enumerate(ys):
            for col, px in enumerate(xs):
                name = names[row][col]
                if name and abs(x - px) <= tolerance and abs(y - py) <= tolerance:
                    return name
        return None

    def _draw_selection(self) -> None:
        self.canvas.delete("selection")
        if not self.selection:
            self._update_sel_label()
            return
        cx0, cy0, cx1, cy1 = self._selection_canvas()
        self.canvas.create_rectangle(cx0, cy0, cx1, cy1, outline=RED,
                                     width=2, dash=(6, 4), tags="selection")
        xs = (cx0, (cx0 + cx1) / 2, cx1)
        ys = (cy0, (cy0 + cy1) / 2, cy1)
        for py in ys:
            for px in xs:
                if (px, py) in ((cx0, cy0), (cx1, cy0), (cx0, cy1),
                                (cx1, cy1), (xs[1], cy0), (xs[1], cy1),
                                (cx0, ys[1]), (cx1, ys[1])):
                    self.canvas.create_rectangle(
                        px - 4, py - 4, px + 4, py + 4, fill="white",
                        outline=RED, width=2, tags="selection")
        self._update_sel_label()

    def _on_motion(self, event) -> None:
        placements = self._placements()
        if (self.selected_placement is not None and
                0 <= self.selected_placement < len(placements)):
            rect = self._placement_rect(placements[self.selected_placement])
            if self._handle_at(event.x, event.y, rect):
                self.canvas.configure(cursor="sizing")
                return
        if self._placement_at(event.x, event.y) is not None:
            self.canvas.configure(cursor="fleur")
            return
        if not self.selection:
            self.canvas.configure(cursor="crosshair")
            return
        rect = self._selection_canvas()
        if self._handle_at(event.x, event.y, rect):
            self.canvas.configure(cursor="sizing")
        elif rect[0] <= event.x <= rect[2] and rect[1] <= event.y <= rect[3]:
            self.canvas.configure(cursor="fleur")
        else:
            self.canvas.configure(cursor="crosshair")

    def _store_selection(self) -> None:
        if not self.selection or not self.pages:
            return
        if self.current_page >= len(self.pages):
            return
        self.page_selections[self.current_page] = self.selection
        if self.apply_all.get():
            for index in range(len(self.pages)):
                self.page_selections[index] = self.selection

    def _on_apply_all(self) -> None:
        if self.apply_all.get() and self.selection and self.pages:
            for index in range(len(self.pages)):
                self.page_selections[index] = self.selection
            self.status.set("área aplicada a todas as páginas")
        self._update_sel_label()

    # ------------------------------------------------------------ imagens
    def _placements(self) -> list[dict]:
        if not self.pages:
            return []
        return self.pages[self.current_page].setdefault("placements", [])

    def _placement_rect(self, placement: dict) -> tuple[float, float, float, float]:
        ox, oy = self.origin
        s = self.scale
        return (ox + placement["x"] * s, oy + placement["y"] * s,
                ox + (placement["x"] + placement["w"]) * s,
                oy + (placement["y"] + placement["h"]) * s)

    def _placement_at(self, x: float, y: float) -> int | None:
        placements = self._placements()
        for index in range(len(placements) - 1, -1, -1):
            x0, y0, x1, y1 = self._placement_rect(placements[index])
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index
        return None

    def _draw_placement_selection(self) -> None:
        self.canvas.delete("placement")
        placements = self._placements()
        if (self.selected_placement is None or
                not 0 <= self.selected_placement < len(placements)):
            return
        placement = placements[self.selected_placement]
        x0, y0, x1, y1 = self._placement_rect(placement)
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=ACCENT,
                                     width=2, tags="placement")
        xs = (x0, (x0 + x1) / 2, x1)
        ys = (y0, (y0 + y1) / 2, y1)
        for py in ys:
            for px in xs:
                self.canvas.create_rectangle(
                    px - 4, py - 4, px + 4, py + 4, fill="white",
                    outline=ACCENT, width=2, tags="placement")
        self.canvas.create_text(
            x0 + 2, y0 - 6,
            text=f"{placement['w'] / DPI:.1f} × {placement['h'] / DPI:.1f} mm",
            anchor="sw", fill=ACCENT, font=(self.font, 8), tags="placement")

    def _refresh_page(self) -> None:
        if not self.pages:
            return
        index = self.current_page
        self._page_cache.pop(index, None)
        self.page_image = self._render_page(index)
        self._page_cache[index] = self.page_image
        self.redraw()

    def _on_drop(self, event) -> None:
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [str(event.data)]
        canvas_x = event.x_root - self.canvas.winfo_rootx()
        canvas_y = event.y_root - self.canvas.winfo_rooty()
        for path in paths:
            self.add_image_placement(str(path), canvas_x, canvas_y)

    def add_image_placement(self, path: str,
                            canvas_x: float | None = None,
                            canvas_y: float | None = None) -> None:
        try:
            image = Image.open(path).convert("L")
        except Exception as exc:
            messagebox.showerror("Imagem", f"{Path(path).name}: {exc}")
            return

        if not self.pages:
            self.pages = [{"kind": "blank", "placements": []}]
            self.page_spin.configure(to=1)
            self._show_page(0)

        placements = self._placements()
        max_w = int(self.page_w * 0.75)
        max_h = int(self.page_h * 0.75)
        scale = min(max_w / image.width, max_h / image.height, 4.0)
        width = max(1, int(image.width * scale))
        height = max(1, int(image.height * scale))

        if canvas_x is None or canvas_y is None:
            px, py = self.page_w // 2, self.page_h // 2
        else:
            px, py = self._canvas_to_page(canvas_x, canvas_y)
        x = max(0, min(self.page_w - width, int(px - width / 2)))
        y = max(0, min(self.page_h - height, int(py - height / 2)))

        placements.append({"image": image, "x": x, "y": y,
                           "w": width, "h": height})
        self.selected_placement = len(placements) - 1

        if len(placements) == 1 and self.pages[self.current_page]["kind"] == "blank":
            self.selection = (x, y, x + width, y + height)
            self._store_selection()

        self._refresh_page()
        self.status.set(
            f"imagem {width / DPI:.1f} × {height / DPI:.1f} mm · "
            "arraste para mover · Delete remove")

    def _delete_placement(self, _event=None) -> None:
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, tk.Text, tk.Spinbox,
                               ttk.Entry, ttk.Combobox)):
            return
        placements = self._placements()
        if (self.selected_placement is None or
                not 0 <= self.selected_placement < len(placements)):
            return
        del placements[self.selected_placement]
        self.selected_placement = None
        self._refresh_page()
        self.status.set("imagem removida")

    # ------------------------------------------------------------ seleção
    def _canvas_to_page(self, x: float, y: float) -> tuple[int, int]:
        ox, oy = self.origin
        px = int((x - ox) / self.scale)
        py = int((y - oy) / self.scale)
        return (max(0, min(self.page_w, px)),
                max(0, min(self.page_h, py)))

    def _on_press(self, event) -> None:
        placements = self._placements()
        if (self.selected_placement is not None and
                0 <= self.selected_placement < len(placements)):
            rect = self._placement_rect(placements[self.selected_placement])
            handle = self._handle_at(event.x, event.y, rect)
            if handle:
                self.placement_drag_mode = "resize"
                self.placement_edge = handle
                self.placement_start = self._canvas_to_page(event.x, event.y)
                self.placement_origin = dict(
                    placements[self.selected_placement])
                return

        hit = self._placement_at(event.x, event.y)
        if hit is not None:
            self.selected_placement = hit
            self.placement_drag_mode = "move"
            self.placement_start = self._canvas_to_page(event.x, event.y)
            self.placement_origin = dict(placements[hit])
            self._draw_placement_selection()
            return

        if self.selected_placement is not None:
            self.selected_placement = None
            self._draw_placement_selection()

        if self.selection:
            rect = self._selection_canvas()
            handle = self._handle_at(event.x, event.y, rect)
            if handle:
                self.drag_mode = "resize"
                self.resize_edge = handle
                self.drag_start = self._canvas_to_page(event.x, event.y)
                self.selection_origin = self.selection
                return
            if rect[0] <= event.x <= rect[2] and rect[1] <= event.y <= rect[3]:
                self.drag_mode = "move"
                self.drag_start = self._canvas_to_page(event.x, event.y)
                self.selection_origin = self.selection
                return

        self.drag_mode = "new"
        self.drag_start = self._canvas_to_page(event.x, event.y)
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)
        self.drag_rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline=RED, width=2,
            dash=(4, 3), tags="rubber")

    def _on_drag(self, event) -> None:
        if self.placement_drag_mode and self.selected_placement is not None:
            placements = self._placements()
            if (self.placement_origin and self.placement_start and
                    0 <= self.selected_placement < len(placements)):
                origin = self.placement_origin
                current = placements[self.selected_placement]
                px, py = self._canvas_to_page(event.x, event.y)
                sx, sy = self.placement_start
                if self.placement_drag_mode == "move":
                    dx, dy = px - sx, py - sy
                    dx = max(-origin["x"], min(
                        self.page_w - origin["x"] - origin["w"], dx))
                    dy = max(-origin["y"], min(
                        self.page_h - origin["y"] - origin["h"], dy))
                    current["x"] = origin["x"] + dx
                    current["y"] = origin["y"] + dy
                else:
                    left, top = origin["x"], origin["y"]
                    right = left + origin["w"]
                    bottom = top + origin["h"]
                    edge = self.placement_edge or ""
                    if "w" in edge:
                        left = min(px, right - 8)
                    if "e" in edge:
                        right = max(px, left + 8)
                    if "n" in edge:
                        top = min(py, bottom - 8)
                    if "s" in edge:
                        bottom = max(py, top + 8)
                    left = max(0, left)
                    top = max(0, top)
                    right = min(self.page_w, right)
                    bottom = min(self.page_h, bottom)
                    current["x"], current["y"] = left, top
                    current["w"], current["h"] = right - left, bottom - top
                self._refresh_page()
            return

        if not self.drag_start:
            return
        if self.drag_mode == "new":
            if not self.drag_rect:
                return
            ox, oy = self.origin
            sx = ox + self.drag_start[0] * self.scale
            sy = oy + self.drag_start[1] * self.scale
            self.canvas.coords(self.drag_rect, sx, sy, event.x, event.y)
            return

        if not self.selection_origin:
            return
        px, py = self._canvas_to_page(event.x, event.y)
        sx, sy = self.drag_start
        x0, y0, x1, y1 = self.selection_origin

        if self.drag_mode == "move":
            dx, dy = px - sx, py - sy
            dx = max(-x0, min(self.page_w - x1, dx))
            dy = max(-y0, min(self.page_h - y1, dy))
            self.selection = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        elif self.drag_mode == "resize":
            left, top, right, bottom = x0, y0, x1, y1
            edge = self.resize_edge or ""
            if "w" in edge:
                left = min(px, right - 8)
            if "e" in edge:
                right = max(px, left + 8)
            if "n" in edge:
                top = min(py, bottom - 8)
            if "s" in edge:
                bottom = max(py, top + 8)
            left = max(0, left)
            top = max(0, top)
            right = min(self.page_w, right)
            bottom = min(self.page_h, bottom)
            self.selection = (left, top, right, bottom)
        self._draw_selection()

    def _on_release(self, event) -> None:
        if self.placement_drag_mode:
            self.placement_drag_mode = None
            self.placement_edge = None
            self.placement_origin = None
            self.placement_start = None
            self._refresh_page()
            placements = self._placements()
            if (self.selected_placement is not None and
                    0 <= self.selected_placement < len(placements)):
                placement = placements[self.selected_placement]
                self.status.set(
                    f"imagem {placement['w'] / DPI:.1f} × "
                    f"{placement['h'] / DPI:.1f} mm")
            return

        mode = self.drag_mode
        self.drag_mode = None
        self.resize_edge = None
        if not self.drag_start:
            return

        if mode == "new":
            x0, y0 = self.drag_start
            x1, y1 = self._canvas_to_page(event.x, event.y)
            self.drag_start = None
            if self.drag_rect:
                self.canvas.delete(self.drag_rect)
                self.drag_rect = None
            x0, x1 = sorted((x0, x1))
            y0, y1 = sorted((y0, y1))
            if x1 - x0 >= 8 and y1 - y0 >= 8:
                self.selection = (x0, y0, x1, y1)
        else:
            self.drag_start = None

        self.selection_origin = None
        if self.selection:
            self._store_selection()
            self._draw_selection()

    def select_all(self) -> None:
        self.selection = (0, 0, self.page_w, self.page_h)
        self._store_selection()
        self.redraw()

    def _update_sel_label(self) -> None:
        if not self.selection:
            self.sel_label.configure(text="área fixa · arraste as alças")
            return
        x0, y0, x1, y1 = self.selection
        text = (f"{(x1 - x0) / DPI:.1f} × {(y1 - y0) / DPI:.1f} mm   "
                f"({x1 - x0} × {y1 - y0} dots)")
        if self.apply_all.get():
            text += "   ·  todas"
        self.sel_label.configure(text=text)

    # ----------------------------------------------------------- páginas
    def _fit_page(self, image: Image.Image) -> Image.Image:
        image = image.convert("L")
        ratio = min(self.page_w / image.width,
                    self.page_h / image.height, 1.0)
        size = (max(1, int(image.width * ratio)),
                max(1, int(image.height * ratio)))
        if size != image.size:
            image = image.resize(size, Image.LANCZOS)
        page = Image.new("L", (self.page_w, self.page_h), 255)
        x = (self.page_w - image.width) // 2
        page.paste(image, (x, 0))
        return page

    def _render_pdf(self, path: str, number: int) -> Image.Image:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "page"
            subprocess.run(
                ["pdftoppm", "-f", str(number), "-l", str(number),
                 "-r", "203", "-png", "-singlefile", path, str(out)],
                check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            return self._fit_page(Image.open(out.with_suffix(".png")))

    def _render_base(self, index: int) -> Image.Image:
        if index in self._base_cache:
            return self._base_cache[index]
        entry = self.pages[index]
        if entry["kind"] == "image":
            base = self._fit_page(Image.open(entry["path"]))
        elif entry["kind"] == "pdf":
            base = self._render_pdf(entry["path"], entry["index"])
        else:
            base = Image.new("L", (self.page_w, self.page_h), 255)
            if entry["kind"] == "text":
                base.paste(render.text_image(entry["text"], self.page_w),
                           (0, 0))
        self._base_cache[index] = base
        return base

    def _render_page(self, index: int) -> Image.Image:
        page = self._render_base(index).copy()
        for placement in self.pages[index].setdefault("placements", []):
            image = placement["image"].convert("L").resize(
                (max(1, int(placement["w"])), max(1, int(placement["h"]))),
                Image.LANCZOS)
            page.paste(image, (int(placement["x"]), int(placement["y"])))
        return page

    def _clear_pages(self) -> None:
        self.pages = []
        self.current_page = 0
        self._page_cache.clear()
        self._base_cache.clear()
        self.page_selections.clear()
        self.selected_placement = None
        self.selection = (0, 0, self.page_w, self.page_h)

    def _default_selection(self, index: int) -> tuple[int, int, int, int]:
        entry = self.pages[index]
        try:
            if entry["kind"] == "image":
                image = Image.open(entry["path"])
                ratio = min(self.page_w / image.width,
                            self.page_h / image.height, 1.0)
                width = max(1, int(image.width * ratio))
                height = max(1, int(image.height * ratio))
                x = (self.page_w - width) // 2
                return (x, 0, x + width, height)
            if entry["kind"] == "text":
                image = render.text_image(entry["text"], self.page_w)
                return (0, 0, self.page_w, min(self.page_h,
                                               image.height))
        except Exception:
            pass
        return (0, 0, self.page_w, self.page_h)

    def _show_page(self, index: int) -> None:
        if not self.pages:
            return
        index = max(0, min(len(self.pages) - 1, index))
        self.current_page = index
        if index not in self._page_cache:
            self.status.set(f"renderizando página {index + 1}…")
            self._page_cache[index] = self._render_page(index)
        self.page_image = self._page_cache[index]
        if index not in self.page_selections:
            self.page_selections[index] = self._default_selection(index)
        self.selection = self.page_selections[index]
        self.page_index.set(index + 1)
        self.page_total.set(f"de {len(self.pages)}")
        self.page_spin.configure(to=max(1, len(self.pages)))
        self.selected_placement = None
        if self.apply_all.get():
            for i in range(len(self.pages)):
                self.page_selections[i] = self.selection
        self.redraw()
        self.status.set(f"página {index + 1} de {len(self.pages)}")

    def goto_page(self, index: int) -> None:
        self._show_page(index)

    def _goto_spin(self) -> None:
        self._show_page(int(self.page_index.get()) - 1)

    def open_image(self) -> None:
        paths = filedialog.askopenfilenames(
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.gif *.tif")])
        if not paths:
            return
        self._clear_pages()
        self.pages = [{"kind": "image", "path": path, "placements": []}
                      for path in paths]
        self._show_page(0)

    @staticmethod
    def _pdf_page_count(path: str) -> int:
        try:
            out = subprocess.run(["pdfinfo", path], capture_output=True,
                                 text=True, timeout=20).stdout
            match = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
            return int(match.group(1)) if match else 1
        except Exception:
            return 1

    def open_pdf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        count = self._pdf_page_count(path)
        self._clear_pages()
        self.pages = [{"kind": "pdf", "path": path, "index": page + 1,
                       "placements": []} for page in range(count)]
        self.pdf_path = path
        self._show_page(0)

    def reload_pdf(self) -> None:
        if not self.pages:
            return
        if self.pages[self.current_page]["kind"] != "pdf":
            return
        self._page_cache.pop(self.current_page, None)
        self._show_page(self.current_page)

    def open_text(self) -> None:
        win = tk.Toplevel(self)
        win.title("Imprimir texto")
        win.geometry("480x440")
        win.configure(bg=BG)
        text = tk.Text(win, wrap="word", font=(self.mono, 11), bg=CARD2,
                       fg=FG, insertbackground=FG, relief="flat", bd=0,
                       highlightthickness=1, highlightbackground=BORDER,
                       padx=12, pady=12)
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.insert("1.0", "Olá!\n\nDigite o texto aqui.")

        def apply() -> None:
            value = text.get("1.0", "end").rstrip()
            win.destroy()
            try:
                image = render.text_image(value, self.page_w)
                self._clear_pages()
                self.pages = [{"kind": "text", "text": value,
                               "placements": []}]
                self._show_page(0)
                self.selection = (0, 0, self.page_w, image.height)
                self.redraw()
                self.status.set("texto carregado")
            except Exception as exc:
                messagebox.showerror("Erro", str(exc))

        self._button(win, "Usar texto", apply, bg=ACCENT, fg=BG,
                     hover=ACCENT_HOVER, bold=True).pack(
            fill="x", padx=12, pady=(0, 12))
        win.transient(self)

    # ---------------------------------------------------------- impressão
    def _raster_for(self, image: Image.Image,
                    selection: tuple[int, int, int, int] | None,
                    keep_position: bool) -> tuple[bytes, int, int]:
        if not selection:
            selection = (0, 0, self.page_w, self.page_h)
        x0, y0, x1, y1 = selection
        crop = image.crop((x0, y0, x1, y1))

        if keep_position:
            width, height = x1, y1
            canvas = Image.new("L", (width, height), 255)
            canvas.paste(crop, (x0, y0))
        else:
            width, height = x1 - x0, y1 - y0
            canvas = crop

        width = min(MAX_WIDTH, max(8, (width + 7) // 8 * 8))
        if canvas.width != width:
            padded = Image.new("L", (width, canvas.height), 255)
            padded.paste(canvas, (0, 0))
            canvas = padded
        return render.pack_bilevel(canvas), width, height

    def _raster(self) -> tuple[bytes, int, int]:
        return self._raster_for(
            self.page_image,
            self.selection or (0, 0, self.page_w, self.page_h),
            self.keep_position.get())

    def _job_for(self, image: Image.Image,
                 selection: tuple[int, int, int, int] | None,
                 keep_position: bool, density: int, speed: int,
                 algorithm: int, paper_type: int) -> tuple[bytes, int, int]:
        raster, width, height = self._raster_for(
            image, selection, keep_position)
        stride = width // 8

        def encode(top: int, rows: int) -> bytes:
            chunk = raster[top * stride:(top + rows) * stride]
            return jbig.encode_pbm(width, rows, chunk)

        data = protocol.build_job(
            width, height, encode, density=density, speed=speed,
            paper_type=paper_type, algorithm=algorithm)
        return data, width, height

    def _job(self) -> tuple[bytes, int, int]:
        return self._job_for(
            self.page_image, self.selection, self.keep_position.get(),
            self.density.get(), self.speed.get(), self.algorithm.get(),
            2 if self.eject.get() else 1)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        if busy:
            self.print_btn._base_bg = TRACK
            self.print_btn.configure(state=tk.DISABLED, bg=TRACK, fg=MUTED,
                                     text="IMPRIMINDO…")
        else:
            self.print_btn._base_bg = ACCENT
            self.print_btn.configure(state=tk.NORMAL, bg=ACCENT, fg=BG,
                                     text="IMPRIMIR PÁGINA")

    def _run(self, title: str, func) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status.set(title)

        def worker() -> None:
            try:
                func()
            except Exception as exc:
                self.after(0, lambda e=exc: self._done(f"erro: {e}"))
            else:
                self.after(0, lambda: self._done("concluído"))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, message: str) -> None:
        self._set_busy(False)
        self.status.set(message)

    def _send(self, data: bytes) -> None:
        with Printer(self._mac()) as printer:
            printer.send(data, delay=0.02, read_timeout=2.0)

    def print_job(self) -> None:
        if self.busy:
            return
        try:
            data, width, height = self._job()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return
        self._run(f"imprimindo {width} dots × {height / DPI:.1f} mm…",
                  lambda: self._send(data))

    def print_all(self) -> None:
        if self.busy or not self.pages:
            return
        if len(self.pages) > 1 and not self.eject.get():
            if not messagebox.askyesno(
                    "Várias páginas",
                    "A opção “Ejetar a folha” está desligada.\n\n"
                    "Em folhas A4, ative para separar as páginas.\n"
                    "Sem ela, o papel só para no fim de cada página "
                    "(modo rolo).\n\nContinuar mesmo assim?"):
                return
        total = len(self.pages)
        selections = dict(self.page_selections)
        keep = self.keep_position.get()
        density = self.density.get()
        speed = self.speed.get()
        algorithm = self.algorithm.get()
        paper_type = 2 if self.eject.get() else 1

        def work() -> None:
            with Printer(self._mac()) as printer:
                for index in range(total):
                    self.after(0, lambda i=index: self.status.set(
                        f"página {i + 1} de {total}…"))
                    image = self._render_page(index)
                    selection = selections.get(index)
                    if not selection:
                        selection = self._default_selection(index)
                    data, _width, height = self._job_for(
                        image, selection, keep, density, speed, algorithm,
                        paper_type)
                    response = printer.send(data, delay=0.02,
                                            read_timeout=0.8)
                    if b"\xaa" not in response and b"OK" not in response:
                        printer.wait_done(
                            timeout=max(6.0, height / 8 / max(1, speed) + 4))

        self._run(f"imprimindo {total} página(s)…", work)

    def save_job(self) -> None:
        try:
            data, _width, _height = self._job()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".bin", filetypes=[("Job", "*.bin")])
        if path:
            Path(path).write_bytes(data)
            self.status.set(f"job salvo · {Path(path).name}")

    def feed(self) -> None:
        mm = max(1, int(self.feed_mm.get()))
        rows = mm * DPI
        raster = render.blank(self.page_w, rows)
        stride = self.page_w // 8

        def encode(top: int, count: int) -> bytes:
            return jbig.encode_pbm(
                self.page_w, count,
                raster[top * stride:(top + count) * stride])

        data = protocol.build_job(
            self.page_w, rows, encode, density=self.density.get(),
            speed=self.speed.get(), paper_type=1)
        self._run(f"avançando {mm} mm…", lambda: self._send(data))

    def query_status(self) -> None:
        def worker() -> None:
            try:
                with Printer(self._mac()) as printer:
                    response = printer.send(protocol.STATUS_QUERY, delay=0,
                                            read_timeout=2.0)
                try:
                    status = json.loads(response.decode())
                    text = "  ·  ".join(f"{k} {v}" for k, v in status.items())
                except Exception:
                    text = "sem resposta" if not response else response.hex(" ")
            except Exception as exc:
                text = f"erro: {exc}"
            self.after(0, lambda t=text: self.status.set(t))

        if not self.busy:
            self.status.set("consultando…")
            threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------- dispositivos
    @staticmethod
    def _query_devices() -> list[tuple[str, str]]:
        try:
            out = subprocess.run(
                ["bluetoothctl", "devices"], capture_output=True,
                text=True, timeout=6).stdout
        except Exception:
            return []
        items: list[tuple[str, str]] = []
        for line in out.splitlines():
            match = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s*(.*)", line)
            if match:
                mac = match.group(1).upper()
                name = match.group(2).strip() or "(sem nome)"
                items.append((name, mac))
        items.sort(key=lambda item: (
            not any(k in item[0].upper() for k in ("X8", "PRINT", "IMPRESS")),
            item[0].upper()))
        return items

    def _apply_devices(self, entries: list[tuple[str, str]]) -> None:
        self.devices = {f"{name}  [{mac}]": mac for name, mac in entries}
        values = list(self.devices)
        self.device_cb.configure(values=values)
        current = self._mac()
        for label, mac in self.devices.items():
            if mac == current:
                self.device.set(label)
                break
        else:
            if values:
                self.device.set(values[0])
        self.status.set(f"{len(values)} dispositivo(s) conhecido(s)")

    @staticmethod
    def _parse_mac(text: str) -> str:
        match = re.search(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", text or "")
        return match.group(0).upper() if match else ""

    def _mac(self) -> str:
        return self._parse_mac(self.device.get()) or DEFAULT_MAC

    def refresh_devices_async(self) -> None:
        self.status.set("listando dispositivos…")

        def work() -> None:
            entries = self._query_devices()
            self.after(0, lambda e=entries: self._apply_devices(e))

        threading.Thread(target=work, daemon=True).start()

    def scan_devices_async(self) -> None:
        self.status.set("escaneando por 8 s…")

        def work() -> None:
            try:
                subprocess.run(
                    ["bluetoothctl", "--timeout", "8", "scan", "on"],
                    capture_output=True, text=True, timeout=20)
            except Exception:
                pass
            entries = self._query_devices()
            self.after(0, lambda e=entries: self._apply_devices(e))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ opções
    def _set_density(self, value: int) -> None:
        self.density.set(value)
        self._update_density()

    def _update_density(self) -> None:
        for value, button in self._density_buttons.items():
            selected = value == self.density.get()
            button.configure(bg=ACCENT if selected else CARD2,
                             fg=BG if selected else MUTED,
                             activebackground=ACCENT if selected else TRACK,
                             activeforeground=BG if selected else FG)


def main() -> None:
    app = App()
    if os.environ.get("X8_GUI_TOPMOST"):
        app.attributes("-topmost", True)
    app.mainloop()


if __name__ == "__main__":
    main()
