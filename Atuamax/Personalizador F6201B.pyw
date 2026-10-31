"""Graphical Atuamax personalizer for validated ZTE F6201B firmware."""

from datetime import datetime
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from engine import customize, watch_physical_reset
from factory_auth import discover_router
from brand import load_brand
from recovery import load_stock_files, restore_standard
from theme import APP, build_theme, load_profile


BRAND = load_brand()
ORANGE = BRAND["accent"]


class Personalizer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Personalizador F6201B • " + BRAND["name"])
        self.geometry("760x650")
        self.minsize(680, 590)
        self.configure(bg="#fff8f3")
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.ip = tk.StringVar(value="")
        self.web_user = tk.StringVar(value="multipro")
        self.web_password = tk.StringVar(value="multipro")
        self.message = tk.StringVar(value=BRAND["welcome"])
        self.logo = tk.StringVar(value=str(APP / "resources" / BRAND["logo"]))
        self.set_wifi = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Detectando a F6201B conectada...")
        self.current_action = ""
        self._build()
        self.after(100, self._pump)
        self.after(250, self._auto_detect)

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Accent.TButton", background=ORANGE, foreground="white", padding=(16, 10), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", BRAND["accent_dark"]), ("disabled", "#c7b0a4")])
        style.configure("Subtle.TButton", padding=(12, 9), font=("Segoe UI", 10))
        style.configure("TEntry", padding=5)
        style.configure("TProgressbar", troughcolor="#f5d7c6", background=ORANGE)

        header = tk.Frame(self, bg=ORANGE, padx=22, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="Personalizador F6201B", bg=ORANGE, fg="white", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="Tema " + BRAND["name"] + " • firmware N6 e N7 com seleção automática", bg=ORANGE, fg="#fff1e9", font=("Segoe UI", 10)).pack(anchor="w")

        body = tk.Frame(self, bg="#fff8f3", padx=24, pady=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        row = 0
        tk.Label(body, text="ONT conectada", bg="#fff8f3", fg="#5b3b2c", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=7)
        ttk.Entry(body, textvariable=self.ip).grid(row=row, column=1, sticky="ew", padx=(12, 8), pady=7)
        ttk.Button(body, text="Detectar", command=self._auto_detect, style="Subtle.TButton").grid(row=row, column=2, pady=7)
        row += 1
        self._field(body, row, "Usuário web", self.web_user)
        row += 1
        self._field(body, row, "Senha web", self.web_password, show="•")
        row += 1
        self._field(body, row, "Mensagem de login", self.message)
        row += 1
        tk.Label(body, text="Logo PNG", bg="#fff8f3", fg="#5b3b2c", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=7)
        ttk.Entry(body, textvariable=self.logo).grid(row=row, column=1, sticky="ew", padx=(12, 8), pady=7)
        ttk.Button(body, text="Escolher…", command=self._choose_logo, style="Subtle.TButton").grid(row=row, column=2, pady=7)
        row += 1
        ttk.Checkbutton(body, text="Nomear as redes 2,4 e 5 GHz como " + BRAND["wifi_prefix"] + "_XXXX (últimos 4 caracteres do MAC da ONT)",
                        variable=self.set_wifi).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 8))
        row += 1
        tk.Label(body, text="Basta conectar uma F6201B à Ethernet. A ferramenta identifica IP, firmware e banco ativo antes de personalizar.",
                 bg="#fff8f3", fg="#694f42", wraplength=680, justify="left", font=("Segoe UI", 9)).grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 14))
        row += 1
        buttons = tk.Frame(body, bg="#fff8f3")
        buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.start_button = ttk.Button(buttons, text="Personalizar ONT", command=self._start_customize, style="Accent.TButton")
        self.start_button.pack(side="left")
        self.restore_button = ttk.Button(buttons, text="Restaurar interface ZTE", command=self._start_restore, style="Subtle.TButton")
        self.restore_button.pack(side="left", padx=(10, 0))
        self.reset_button = ttk.Button(buttons, text="Verificar reset físico", command=self._start_reset_watch, style="Subtle.TButton")
        self.reset_button.pack(side="left", padx=10)
        ttk.Button(buttons, text="Abrir backups", command=self._open_backups, style="Subtle.TButton").pack(side="right")
        row += 1
        self.progress = ttk.Progressbar(body, mode="indeterminate", style="TProgressbar")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew")
        row += 1
        tk.Label(body, textvariable=self.status, bg="#fff8f3", fg="#8b3a16", font=("Segoe UI", 10, "bold"), anchor="w").grid(row=row, column=0, columnspan=3, sticky="ew", pady=(9, 9))
        row += 1
        log_frame = tk.Frame(body, bg="#fff8f3")
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew")
        body.rowconfigure(row, weight=1)
        self.logbox = tk.Text(log_frame, wrap="word", height=12, state="disabled", bg="white", fg="#3f342d", font=("Consolas", 9), relief="solid", bd=1)
        self.logbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.logbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.logbox.configure(yscrollcommand=scrollbar.set)

    def _field(self, parent, row, label, variable, show=None):
        tk.Label(parent, text=label, bg="#fff8f3", fg="#5b3b2c", font=("Segoe UI", 10)).grid(row=row, column=0, sticky="w", pady=7)
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=7)

    def _choose_logo(self):
        chosen = filedialog.askopenfilename(title="Escolher logo PNG", filetypes=[("Imagem PNG", "*.png")])
        if chosen:
            self.logo.set(chosen)

    def _open_backups(self):
        folder = APP / "backups"
        folder.mkdir(exist_ok=True)
        os.startfile(str(folder))

    def _log(self, message: str):
        self.events.put(("log", message))

    def _auto_detect(self):
        def work():
            try:
                router = discover_router(self._log)
                self.events.put(("detected", router))
            except Exception as exc:
                self.events.put(("detect_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, value: bool):
        self.busy = value
        state = "disabled" if value else "normal"
        self.start_button.configure(state=state)
        self.restore_button.configure(state=state)
        self.reset_button.configure(state=state)
        if value:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _start_worker(self, task, *args):
        if self.busy:
            return
        self.current_action = task.__name__
        self._set_busy(True)
        def work():
            try:
                result = task(*args, self._log)
                self.events.put(("done", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _start_customize(self):
        self._start_worker(
            customize,
            self.ip.get().strip(), self.web_user.get().strip(), self.web_password.get(),
            self.message.get().strip(), Path(self.logo.get().strip()), self.set_wifi.get(),
        )

    def _start_reset_watch(self):
        messagebox.showinfo("Teste do reset físico", "Depois de fechar esta mensagem, pressione o botão de reset da ONT. A ferramenta aguardará a rede voltar e conferirá o visual. O reset apaga as configurações da ONT.")
        self._start_worker(
            watch_physical_reset, self.ip.get().strip(), self.message.get().strip(),
            Path(self.logo.get().strip()), self.web_user.get().strip(), self.web_password.get(),
            self.set_wifi.get(),
        )

    def _start_restore(self):
        if not messagebox.askyesno(
            "Restaurar interface ZTE",
            "A interface original será restaurada nos dois bancos de firmware. "
            "A ONT reiniciará duas vezes. As configurações de rede e os nomes Wi-Fi serão mantidos. Continuar?",
        ):
            return
        self._start_worker(
            restore_standard,
            self.ip.get().strip(), self.web_user.get().strip(), self.web_password.get(),
        )

    def _pump(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.status.set(value)
                    stamp = datetime.now().strftime("%H:%M:%S")
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", f"[{stamp}] {value}\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "detected":
                    self.ip.set(value)
                    self.status.set("ONT detectada em " + value + ". Pronto para personalizar.")
                elif kind == "detect_error":
                    self.status.set(value)
                elif kind == "done":
                    self._set_busy(False)
                    self.status.set("Concluído.")
                    if self.current_action == "restore_standard":
                        messagebox.showinfo("Interface restaurada", f"Interface ZTE original conferida nos dois bancos.\n\nBackup: {value}")
                    elif isinstance(value, Path):
                        messagebox.showinfo("Personalização concluída", f"Visual aplicado e verificado após reiniciar.\n\nBackup: {value}")
                    else:
                        messagebox.showinfo("Teste concluído", "A personalização permaneceu após o reset físico.")
                elif kind == "error":
                    self._set_busy(False)
                    self.status.set("Processo interrompido: " + value)
                    messagebox.showerror("Não foi possível concluir", value)
        except queue.Empty:
            pass
        self.after(100, self._pump)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        for version in ("V9.3.10P7N6", "V9.3.10P7N7"):
            profile = load_profile(version)
            build_theme(profile, BRAND["welcome"], APP / "resources" / BRAND["logo"])
            load_stock_files(profile)
        window = Personalizer()
        window.withdraw()
        window.update()
        window.destroy()
    else:
        Personalizer().mainloop()
