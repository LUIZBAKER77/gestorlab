import os
import sys
import json
import time
import socket
import asyncio
import base64
import io
import threading
import subprocess
import random
import hashlib
import queue
import webbrowser

# Python embutido: o Tcl/Tk fica em <pasta do python>\tcl e precisa ser apontado antes de importar o tkinter.
_tcl_root = os.path.join(os.path.dirname(sys.executable), "tcl")
if os.path.isdir(_tcl_root):
    os.environ.setdefault("TCL_LIBRARY", os.path.join(_tcl_root, "tcl8.6"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(_tcl_root, "tk8.6"))

import tkinter as tk
import winsound
import websockets
from PIL import Image
import mss
import ctypes
from ctypes import wintypes
import winreg
import urllib.request
import urllib.parse

# Habilitar DPI Awareness para precisão milimétrica de cliques no Windows
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor DPI aware
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

# ==========================================
# Blindagem de Segurança (Low-Level Keyboard Hook)
# ==========================================
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012

HOOKPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG))
    ]

_hook_id = None
_hook_thread = None
_hook_thread_id = None
_hook_proc_ref = None
_hook_ready = threading.Event()
_hook_lock = threading.Lock()

def _keyboard_hook_worker():
    global _hook_id, _hook_thread_id, _hook_proc_ref
    _hook_thread_id = kernel32.GetCurrentThreadId()

    def low_level_keyboard_proc(nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = KBDLLHOOKSTRUCT.from_address(lParam)
            vk = kb.vkCode
            flags = kb.flags
            is_alt = (flags & 0x20) != 0

            # Bloqueia Alt+F4 (0x73), Alt+Tab (0x09), Alt+Esc (0x1B), Alt+Space (0x20)
            if is_alt and vk in (0x73, 0x09, 0x1B, 0x20):
                return 1

            # Bloqueia Teclas Windows (LWIN 0x5B, RWIN 0x5C)
            if vk in (0x5B, 0x5C):
                return 1

            # Bloqueia Ctrl+Esc e atalhos de sistema com Escape (Ctrl+Shift+Esc)
            if vk == 0x1B:
                ctrl_down = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
                if ctrl_down:
                    return 1

        return user32.CallNextHookEx(_hook_id, nCode, wParam, lParam)

    _hook_proc_ref = HOOKPROC(low_level_keyboard_proc)
    _hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _hook_proc_ref, 0, 0)
    _hook_ready.set()

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    if _hook_id:
        user32.UnhookWindowsHookEx(_hook_id)
        _hook_id = None

def install_keyboard_hook():
    global _hook_thread
    with _hook_lock:
        # O teste é pela thread (e não por _hook_id), que só é preenchido depois: evita dois ganchos.
        if _hook_thread and _hook_thread.is_alive():
            return
        _hook_ready.clear()
        _hook_thread = threading.Thread(target=_keyboard_hook_worker, daemon=True)
        _hook_thread.start()

def uninstall_keyboard_hook():
    global _hook_thread, _hook_thread_id
    with _hook_lock:
        if not (_hook_thread and _hook_thread.is_alive()):
            return
        # Se o gancho acabou de ser pedido, espera a thread existir; senão o WM_QUIT se perde.
        _hook_ready.wait(2.0)
        if _hook_thread_id:
            try:
                user32.PostThreadMessageW(_hook_thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        _hook_thread.join(1.0)
        _hook_thread = None
        _hook_thread_id = None

def set_task_manager_disabled(disabled: bool):
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
        if disabled:
            winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1)
        else:
            try:
                winreg.DeleteValue(key, "DisableTaskMgr")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass

def ensure_startup_persistence():
    """Garante o início com o Windows apontando para o lançador (.exe) que iniciou o agente."""
    launcher = os.environ.get("GESTORLAB_LAUNCHER")
    if not launcher or os.path.exists(os.path.join(DATA_DIR, "inicio_manual.txt")):
        return
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "GestorLabAgent", 0, winreg.REG_SZ, f'"{launcher}" --autostart')
        winreg.CloseKey(key)
    except Exception:
        pass

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuração do usuário: pasta "dados" ao lado do .exe (definida pelo lançador) ou a pasta do script.
DATA_DIR = os.environ.get("GESTORLAB_DATA") or APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

# Sem console (pythonw.exe) sys.stdout é None: grava as mensagens em arquivo.
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(DATA_DIR, "agente.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log
LOGO_PATH = os.path.join(APP_DIR, "logo.png")
if not os.path.exists(LOGO_PATH):
    LOGO_PATH = os.path.join(getattr(sys, '_MEIPASS', APP_DIR), "logo.png")

def load_config():
    default_cfg = {
        "server_host": "auto",
        "server_port": 8000,
        "fps_interval": 0.5,
        "jpeg_quality": 40,
        "scale": 0.4,
        "require_student_login": True,
        "class_password": "",
        "agent_key": ""
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return {**default_cfg, **json.load(f)}
        except Exception:
            pass
    return default_cfg

CONFIG = load_config()

HOSTNAME = socket.gethostname()
USERNAME = os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USERNAME", "Aluno")

# Informações do Aluno logado
current_student_data = {
    "student_name": "",
    "matricula": "",
    "is_logged_in": False
}

# ==========================================
# Constantes da Win32 API para Entrada Remota
# ==========================================
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_MAP = {
    "Enter": 0x0D, "Backspace": 0x08, "Tab": 0x09, "Escape": 0x1B, "Space": 0x20, " ": 0x20,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28,
    "Delete": 0x2E, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "Shift": 0x10, "Control": 0x11, "Alt": 0x12, "Meta": 0x5B, "ContextMenu": 0x5D,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "Insert": 0x2D, "CapsLock": 0x14,
}
# Teclas "estendidas": sem esta flag o Windows as trata como as do teclado numérico.
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D}

INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT_UNION(ctypes.Union):
    # MOUSEINPUT é o maior membro; o padding garante o sizeof correto em 32/64 bits.
    _fields_ = [("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def send_unicode_key(char: str, is_up: bool):
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if is_up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(0, ord(char), flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _vk_for_shortcut(code: str):
    """'KeyC' -> VK 'C', 'Digit1' -> VK '1' (para Ctrl+C, Alt+1 etc. funcionarem no aluno)."""
    if code.startswith("Key") and len(code) == 4:
        return ord(code[3].upper())
    if code.startswith("Digit") and len(code) == 6:
        return ord(code[5])
    return None


def _move_cursor(data: dict):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    target_x = max(0, min(sw - 1, int(float(data.get("x", 0)) * sw)))
    target_y = max(0, min(sh - 1, int(float(data.get("y", 0)) * sh)))
    user32.SetCursorPos(target_x, target_y)


def handle_remote_input(data: dict):
    try:
        event_type = data.get("event")

        # O clique traz a posição: o último mouse_move pode ter sido descartado pelo limite de taxa.
        if event_type in ("mouse_move", "mouse_down", "mouse_up") and "x" in data and "y" in data:
            _move_cursor(data)

        if event_type == "mouse_down":
            btn = data.get("button", 0) # 0=left, 1=middle, 2=right
            if btn == 0:
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            elif btn == 2:
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            elif btn == 1:
                user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)

        elif event_type == "mouse_up":
            btn = data.get("button", 0)
            if btn == 0:
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            elif btn == 2:
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            elif btn == 1:
                user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)

        elif event_type == "wheel":
            delta = float(data.get("deltaY", 0))
            if delta == 0:
                return   # rolagem só horizontal: antes virava "rolar para cima"
            wheel_amount = -120 if delta > 0 else 120
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wheel_amount, 0)

        elif event_type in ["key_down", "key_up"]:
            key_name = str(data.get("key", ""))
            is_up = (event_type == "key_up")
            flags = KEYEVENTF_KEYUP if is_up else 0

            shortcut_vk = None
            if len(key_name) == 1 and (data.get("ctrl") or data.get("alt") or data.get("meta")):
                shortcut_vk = _vk_for_shortcut(str(data.get("code", "")))

            if key_name in VK_MAP:
                vk = VK_MAP[key_name]
                if vk in EXTENDED_VKS:
                    flags |= KEYEVENTF_EXTENDEDKEY
                user32.keybd_event(vk, 0, flags, 0)
            elif shortcut_vk:
                # Caractere Unicode não aciona atalhos: com Ctrl/Alt usa a tecla virtual.
                user32.keybd_event(shortcut_vk, 0, flags, 0)
            elif len(key_name) == 1:
                send_unicode_key(key_name, is_up)
    except Exception as e:
        print(f"[RemoteInput Error]: {e}")

# ==========================================
# Descoberta e Validação de Credenciais no Servidor
# ==========================================
ACTIVE_SERVER = {"ip": None, "port": 8000}

def discover_server(discovery_port=8001, timeout=1.2):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    for b_addr in ["<broadcast>", "255.255.255.255"]:
        try:
            sock.sendto(b"GESTORLAB_DISCOVERY_PING", (b_addr, discovery_port))
        except Exception:
            pass

    try:
        data, addr = sock.recvfrom(1024)
        if data.startswith(b"GESTORLAB_SERVER:"):
            parts = data.decode("utf-8").split(":")
            port = int(parts[1]) if len(parts) > 1 else 8000
            ACTIVE_SERVER["ip"] = addr[0]
            ACTIVE_SERVER["port"] = port
            return addr[0], port
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return None, None

def verify_student_with_server(matricula: str, password: str):
    host = ACTIVE_SERVER.get("ip")
    port = ACTIVE_SERVER.get("port", 8000)

    if not host or str(host).lower() in ["auto", ""]:
        configured_host = CONFIG.get("server_host", "auto")
        if configured_host and str(configured_host).lower() not in ["auto", ""]:
            host = configured_host
        else:
            disc_ip, disc_port = discover_server(8001, timeout=1.0)
            if disc_ip:
                host = disc_ip
                port = disc_port

    if not host:
        host = "127.0.0.1"

    url = f"http://{host}:{port}/api/student/verify-login"
    payload = json.dumps({"matricula": matricula, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "X-Agent-Key": CONFIG.get("agent_key", "")})

    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return True, data.get("student")
            return False, data.get("error", "Matrícula ou senha incorretos.")
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            return False, err_data.get("error", "Matrícula ou senha incorretos.")
        except Exception:
            return False, "Matrícula ou senha incorretos."
    except Exception:
        return False, f"Servidor não respondeu ({host}:{port}). Verifique a rede."

# ==========================================
# Gerenciador de Interface (Bloqueio, Lockscreen e Avisos)
# ==========================================
class UIManager:
    def __init__(self):
        self.lock_window = None
        self.login_window = None
        self.is_locked = False
        self.lock_deadline = None   # time.monotonic() em que o timer libera a tela
        self.is_login_locked = False
        self.login_callback = None
        # O Tkinter só pode ser usado pela própria thread: as outras enfileiram pedidos aqui.
        self._queue = queue.Queue()
        self._ready = threading.Event()
        self.ui_thread = threading.Thread(target=self._run_ui_loop, daemon=True)
        self.ui_thread.start()
        self._ready.wait(10)   # evita usar self.root antes de ele existir

    def _run_ui_loop(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self._ready.set()
        self.root.after(50, self._process_events)
        self.root.mainloop()

    def _process_events(self):
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                print(f"[Erro na interface]: {e}")
        self.root.after(50, self._process_events)

    def call(self, fn):
        """Executa fn na thread da interface (seguro a partir de qualquer thread)."""
        self._queue.put(fn)

    def trigger_lock(self, message="Atenção na explicação do professor", duration=0):
        # Timer: o próprio agente libera a tela quando o prazo acaba (mesmo sem rede).
        self.lock_deadline = time.monotonic() + duration if duration > 0 else None
        if self.is_locked:
            self.call(lambda: self._update_lock_message(message))
            return
        self.is_locked = True
        self.call(lambda: self._create_lock_window(message))

    def trigger_unlock(self):
        self.lock_deadline = None
        if not self.is_locked:
            return
        self.is_locked = False
        self.call(self._destroy_lock_window)

    def lock_remaining(self) -> int:
        deadline = getattr(self, "lock_deadline", None)
        if not self.is_locked or deadline is None:
            return 0
        return max(1, int(deadline - time.monotonic()))

    def _tick_lock_timer(self):
        if not (self.is_locked and self.lock_window):
            return
        deadline = getattr(self, "lock_deadline", None)
        if deadline is None:
            self._lock_timer_label.config(text="")
        else:
            left = deadline - time.monotonic()
            if left <= 0:
                self.trigger_unlock()
                send_to_server({"type": "status_ack", "is_locked": False})
                return
            minutes, seconds = divmod(int(left + 0.999), 60)
            self._lock_timer_label.config(text=f"⏱  Liberação automática em {minutes:02d}:{seconds:02d}")
        self.lock_window.after(1000, self._tick_lock_timer)

    def trigger_message(self, title, content):
        self.call(lambda: self._show_message_window(title, content))

    def trigger_toast(self, title, content):
        self.call(lambda: self._show_toast_window(title, content))

    def trigger_student_login(self, callback):
        self.login_callback = callback
        self.is_login_locked = True
        self.call(self._create_student_login_window)

    def trigger_bypass_login(self):
        self.is_login_locked = False
        self.call(self._destroy_student_login_window)

    def _update_lock_message(self, message):
        if self.lock_window and getattr(self, "_lock_msg_label", None):
            self._lock_msg_label.config(text=message)

    def _create_lock_window(self, message):
        if self.lock_window:
            return
        
        # Ativa bloqueio de atalhos em baixo nível e desativa Gerenciador de Tarefas
        install_keyboard_hook()
        set_task_manager_disabled(True)

        win = tk.Toplevel(self.root)
        self.lock_window = win
        win.title("GestorLab - Bloqueado")
        win.configure(bg="#0f172a")
        
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.overrideredirect(True)
        
        # Bloqueia encerramento por eventos de janela e atalhos Tkinter
        win.protocol("WM_DELETE_WINDOW", lambda: "break")
        win.bind("<Alt-F4>", lambda e: "break")
        win.bind("<Escape>", lambda e: "break")
        win.bind("<Alt-Key>", lambda e: "break")
        win.bind("<Control-Key>", lambda e: "break")
        
        # Recupera foco agressivamente se o usuário tentar clicar fora
        win.bind("<FocusOut>", lambda e: win.after(10, lambda: (win.lift(), win.attributes("-topmost", True), win.focus_force())))
        
        def keep_top():
            if self.is_locked and self.lock_window:
                try:
                    win.lift()
                    win.attributes("-topmost", True)
                    win.focus_force()
                    win.after(200, keep_top)
                except Exception:
                    pass
        keep_top()

        container = tk.Frame(win, bg="#0f172a")
        container.place(relx=0.5, rely=0.5, anchor="center")

        icon_label = tk.Label(container, text="🔒", font=("Segoe UI Emoji", 64), bg="#0f172a", fg="#f87171")
        icon_label.pack(pady=(0, 10))

        title_label = tk.Label(
            container, 
            text="COMPUTADOR BLOQUEADO", 
            font=("Segoe UI", 26, "bold"), 
            bg="#0f172a", 
            fg="#f1f5f9"
        )
        title_label.pack(pady=5)

        msg_label = tk.Label(
            container, 
            text=message, 
            font=("Segoe UI", 16), 
            bg="#0f172a", 
            fg="#94a3b8",
            wraplength=700,
            justify="center"
        )
        msg_label.pack(pady=15)
        self._lock_msg_label = msg_label

        sub_label = tk.Label(
            container, 
            text="Aguarde as orientações do professor.", 
            font=("Segoe UI", 12, "italic"), 
            bg="#0f172a", 
            fg="#64748b"
        )
        sub_label.pack(pady=(20, 0))

        self._lock_timer_label = tk.Label(container, text="", font=("Segoe UI", 14, "bold"), bg="#0f172a", fg="#fbbf24")
        self._lock_timer_label.pack(pady=(18, 0))
        self._tick_lock_timer()

    def _destroy_lock_window(self):
        if self.lock_window:
            try:
                self.lock_window.destroy()
            except Exception:
                pass
            self.lock_window = None
        if not self.is_login_locked:
            uninstall_keyboard_hook()
            set_task_manager_disabled(False)

    # ==========================================
    # Tela de Identificação / Login do Aluno (Blindada)
    # ==========================================
    def _create_student_login_window(self):
        if self.login_window:
            return

        # Ativa bloqueio de atalhos e desativa Gerenciador de Tarefas
        install_keyboard_hook()
        set_task_manager_disabled(True)

        win = tk.Toplevel(self.root)
        self.login_window = win
        win.title("GestorLab - Identificação do Aluno")
        win.configure(bg="#0b0f19")
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.overrideredirect(True)

        # Suprime qualquer evento de fechamento de janela
        win.protocol("WM_DELETE_WINDOW", lambda: "break")
        win.bind("<Alt-F4>", lambda e: "break")
        win.bind("<Escape>", lambda e: "break")
        win.bind("<FocusOut>", lambda e: win.after(10, lambda: (win.lift(), win.attributes("-topmost", True), win.focus_force())))

        def keep_top():
            if self.is_login_locked and self.login_window:
                try:
                    win.lift()
                    win.attributes("-topmost", True)
                    win.after(250, keep_top)
                except Exception:
                    pass
        keep_top()

        container = tk.Frame(win, bg="#1e293b", bd=1, relief="solid", padx=40, pady=35)
        container.place(relx=0.5, rely=0.5, anchor="center")

        # Título
        lbl_head = tk.Label(container, text="🎓 GestorLab • Laboratório", font=("Segoe UI", 14, "bold"), bg="#1e293b", fg="#818cf8")
        lbl_head.pack(pady=(0, 4))

        lbl_sub = tk.Label(container, text="Digite sua Matrícula e Senha para liberar o computador", font=("Segoe UI", 11), bg="#1e293b", fg="#94a3b8")
        lbl_sub.pack(pady=(0, 20))

        # Campo Matrícula
        lbl_mat = tk.Label(container, text="Número de Matrícula (ou Código):", font=("Segoe UI", 10, "bold"), bg="#1e293b", fg="#f1f5f9", anchor="w")
        lbl_mat.pack(fill="x", pady=(5, 2))
        entry_mat = tk.Entry(container, font=("Segoe UI", 12), bg="#0f172a", fg="#ffffff", insertbackground="white", bd=1, relief="solid")
        entry_mat.pack(fill="x", ipady=5, pady=(0, 12))

        # Campo Senha
        lbl_pass = tk.Label(container, text="Senha de Acesso:", font=("Segoe UI", 10, "bold"), bg="#1e293b", fg="#f1f5f9", anchor="w")
        lbl_pass.pack(fill="x", pady=(5, 2))
        
        pass_frame = tk.Frame(container, bg="#1e293b")
        pass_frame.pack(fill="x", pady=(0, 4))

        entry_pass = tk.Entry(pass_frame, font=("Segoe UI", 12), bg="#0f172a", fg="#ffffff", insertbackground="white", show="•", bd=1, relief="solid")
        entry_pass.pack(side="left", fill="x", expand=True, ipady=5)

        def toggle_pass_visibility():
            if entry_pass.cget("show") == "":
                entry_pass.config(show="•")
                btn_toggle_pass.config(text="👁️ Ver")
            else:
                entry_pass.config(show="")
                btn_toggle_pass.config(text="🙈 Ocultar")

        btn_toggle_pass = tk.Button(pass_frame, text="👁️ Ver", font=("Segoe UI", 9), bg="#334155", fg="#cbd5e1", relief="flat", padx=8, cursor="hand2", command=toggle_pass_visibility)
        btn_toggle_pass.pack(side="right", padx=(5, 0), ipady=3)

        lbl_status = tk.Label(container, text="", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#f87171", wraplength=340, justify="center")
        lbl_status.pack(pady=(8, 12))

        def submit_login():
            mat = entry_mat.get().strip()
            pwd = entry_pass.get().strip()
            if not mat or not pwd:
                lbl_status.config(text="Preencha a Matrícula e a Senha.", fg="#f87171")
                return

            lbl_status.config(text="Verificando credenciais no servidor...", fg="#38bdf8")
            btn_entrar.config(state="disabled", text="Autenticando...")

            def verify_worker():
                ok, res = verify_student_with_server(mat, pwd)
                def on_done():
                    if ok:
                        lbl_status.config(text=f"Acesso liberado! Olá, {res.get('name', 'Aluno')}", fg="#34d399")
                        try:
                            winsound.MessageBeep(winsound.MB_OK)
                        except Exception:
                            pass
                        win.after(600, lambda: self._on_student_authenticated(res))
                    else:
                        lbl_status.config(text=res if isinstance(res, str) else "Matrícula ou senha incorretos.", fg="#f87171")
                        btn_entrar.config(state="normal", text="Entrar no Computador")
                        entry_pass.delete(0, tk.END)
                        entry_pass.focus_set()

                self.call(on_done)   # esta função roda numa thread auxiliar

            threading.Thread(target=verify_worker, daemon=True).start()

        btn_entrar = tk.Button(
            container,
            text="Entrar no Computador",
            font=("Segoe UI", 11, "bold"),
            bg="#4f46e5",
            fg="#ffffff",
            activebackground="#4338ca",
            activeforeground="#ffffff",
            relief="flat",
            cursor="hand2",
            command=submit_login
        )
        btn_entrar.pack(fill="x", ipady=6, pady=(5, 0))

        win.bind("<Return>", lambda e: submit_login())
        entry_mat.focus_set()

    def _on_student_authenticated(self, student_info):
        self._destroy_student_login_window()
        if self.login_callback:
            self.login_callback(
                student_info.get("name", "Aluno"),
                student_info.get("matricula", ""),
                student_info.get("turma", "")
            )

    def _destroy_student_login_window(self):
        self.is_login_locked = False
        if self.login_window:
            try:
                self.login_window.destroy()
            except Exception:
                pass
            self.login_window = None
        if not self.is_locked:
            uninstall_keyboard_hook()
            set_task_manager_disabled(False)

    def _show_message_window(self, title, content):
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg="#1e293b")
        win.attributes("-topmost", True)
        win.resizable(False, False)

        w, h = 480, 240
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

        header = tk.Frame(win, bg="#334155", height=42)
        header.pack(fill="x", side="top")
        
        t_label = tk.Label(header, text=f"📢  {title}", font=("Segoe UI", 12, "bold"), bg="#334155", fg="#ffffff")
        t_label.pack(side="left", padx=15, pady=10)

        body = tk.Frame(win, bg="#1e293b", padx=20, pady=20)
        body.pack(fill="both", expand=True)

        c_label = tk.Label(body, text=content, font=("Segoe UI", 11), bg="#1e293b", fg="#e2e8f0", wraplength=440, justify="center")
        c_label.pack(expand=True, fill="both")

        btn_frame = tk.Frame(win, bg="#1e293b", pady=10)
        btn_frame.pack(fill="x", side="bottom")

        btn = tk.Button(
            btn_frame, 
            text="Entendido / OK", 
            font=("Segoe UI", 10, "bold"), 
            bg="#3b82f6", 
            fg="#ffffff", 
            activebackground="#2563eb", 
            activeforeground="#ffffff", 
            relief="flat", 
            padx=20, 
            pady=6, 
            cursor="hand2", 
            command=win.destroy
        )
        btn.pack(anchor="center")
        win.focus_force()

    def _show_toast_window(self, title, content):
        try:
            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass

        toast = tk.Toplevel(self.root)
        toast.title(title)
        toast.configure(bg="#0f172a")
        toast.attributes("-topmost", True)
        toast.overrideredirect(True)

        w, h = 360, 110
        sw = toast.winfo_screenwidth()
        sh = toast.winfo_screenheight()
        x = sw - w - 20
        y = sh - h - 60
        toast.geometry(f"{w}x{h}+{x}+{y}")

        card = tk.Frame(toast, bg="#1e293b", bd=1, relief="solid")
        card.pack(fill="both", expand=True)

        t_lbl = tk.Label(card, text=title, font=("Segoe UI", 10, "bold"), bg="#1e293b", fg="#38bdf8", anchor="w")
        t_lbl.pack(fill="x", padx=12, pady=(10, 4))

        m_lbl = tk.Label(card, text=content, font=("Segoe UI", 9), bg="#1e293b", fg="#e2e8f0", wraplength=330, justify="left", anchor="w")
        m_lbl.pack(fill="x", padx=12, pady=(0, 10))

        # Auto-destruir após 6 segundos
        toast.after(6000, lambda: toast.destroy())

ui_manager = UIManager()

# ==========================================
# Captura de Tela Resiliente (mss + Fallback)
# ==========================================
stream_settings = {
    "interval": float(CONFIG.get("fps_interval", 0.5)),
    "scale": float(CONFIG.get("scale", 0.4)),
    "quality": int(CONFIG.get("jpeg_quality", 40)),
    "paused": False,   # o servidor pausa o envio quando nenhum painel está aberto
}
DEFAULT_STREAM = dict(stream_settings)

KEEPALIVE_SECONDS = 5.0   # quadro parado é reenviado só a cada tanto
_last_frame_hash = None
_last_frame_sent = 0.0

def capture_screen_base64(sct_instance, scale=0.5, quality=45):
    """Captura a tela em JPEG/base64. Devolve None se a tela não mudou (poupa rede e CPU).

    Levanta exceção se a captura falhar (ex.: tela do UAC ou Ctrl+Alt+Del): quem chama
    decide recriar o mss. Antes o erro era engolido e a mesma imagem velha era reenviada
    para sempre, deixando a tela "congelada" no painel.
    """
    global _last_frame_hash, _last_frame_sent
    monitor = sct_instance.monitors[1]
    screenshot = sct_instance.grab(monitor)

    img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    if scale != 1.0:
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        img = img.resize((new_w, new_h), Image.Resampling.BILINEAR)

    digest = hashlib.blake2b(img.tobytes(), digest_size=8).digest()
    now = time.monotonic()
    if digest == _last_frame_hash and now - _last_frame_sent < KEEPALIVE_SECONDS:
        return None
    _last_frame_hash, _last_frame_sent = digest, now

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=False, subsampling=2)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"

# ==========================================
# Comunicação WebSocket com o Professor
# ==========================================
async def handle_commands(ws):
    while True:
        try:
            msg_str = await ws.recv()
            data = json.loads(msg_str)
            action = data.get("action")

            if action == "lock":
                lock_msg = data.get("message") or "Atenção na explicação do professor."
                try:
                    duration = max(0, min(int(float(data.get("duration") or 0)), 4 * 3600))
                except (TypeError, ValueError):
                    duration = 0
                ui_manager.trigger_lock(lock_msg, duration)
                await ws.send(json.dumps({"type": "status_ack", "is_locked": True,
                                          "lock_remaining": ui_manager.lock_remaining()}))

            elif action == "set_rules":
                apply_rules(data, persist=True)

            elif action == "unlock":
                ui_manager.trigger_unlock()
                await ws.send(json.dumps({"type": "status_ack", "is_locked": False}))

            elif action == "message":
                title = data.get("title", "Aviso do Professor")
                content = data.get("content", "")
                ui_manager.trigger_message(title, content)

            elif action == "set_stream_settings":
                # Limites: escala 0 derrubava a captura; qualidade fora de 1..95 dá erro no JPEG.
                if "interval" in data:
                    stream_settings["interval"] = min(5.0, max(0.04, float(data["interval"])))
                if "scale" in data:
                    stream_settings["scale"] = min(1.0, max(0.1, float(data["scale"])))
                if "quality" in data:
                    stream_settings["quality"] = min(95, max(10, int(data["quality"])))

            elif action == "open_url":
                url = str(data.get("url", "")).strip()
                if urllib.parse.urlsplit(url).scheme.lower() in ("http", "https"):
                    webbrowser.open(url)
                    ui_manager.trigger_toast("🌐 Site aberto pelo professor", url[:120])

            elif action == "reset_stream":
                paused = stream_settings["paused"]
                stream_settings.update(DEFAULT_STREAM)
                stream_settings["paused"] = paused

            elif action == "stream_pause":
                stream_settings["paused"] = True

            elif action == "stream_resume":
                stream_settings["paused"] = False
                global _last_frame_hash
                _last_frame_hash = None   # força o envio imediato de um quadro novo

            elif action == "remote_input":
                # Controle remoto de mouse e teclado
                handle_remote_input(data)

            elif action == "power":
                # Gerenciamento de Energia (Desligar / Reiniciar)
                mode = data.get("mode", "shutdown")
                if mode == "shutdown":
                    subprocess.Popen(["shutdown", "/s", "/t", "3", "/f", "/c", "Desligamento solicitado pelo professor."])
                elif mode == "reboot":
                    subprocess.Popen(["shutdown", "/r", "/t", "3", "/f", "/c", "Reinicializacao solicitada pelo professor."])

            elif action == "receive_file":
                # Recebimento de Arquivo enviado pelo professor
                try:
                    filename = os.path.basename(str(data.get("filename", "")).replace("\\", "/")) or "arquivo_professor.bin"
                    # Decodificar e gravar fora do loop: arquivos grandes travavam a tela e os comandos.
                    save_path = await asyncio.to_thread(save_received_file, filename, data.get("data", ""))

                    ui_manager.trigger_toast("📁 Arquivo Recebido!", f"'{filename}' foi salvo na sua Área de Trabalho.")
                    await ws.send(json.dumps({
                        "type": "file_received_ack",
                        "filename": filename,
                        "path": save_path,
                        "status": "ok"
                    }))
                except Exception as ex:
                    print(f"[Erro ao salvar arquivo]: {ex}")
                    await ws.send(json.dumps({
                        "type": "file_received_ack",
                        "filename": str(data.get("filename", "")),
                        "path": "",
                        "status": "error"
                    }))

            elif action == "student_logout":
                # Força a tela de bloqueio para novo aluno logar
                current_student_data["is_logged_in"] = False
                current_student_data["student_name"] = ""
                current_student_data["matricula"] = ""
                current_student_data["turma"] = ""
                ui_manager.trigger_student_login(on_login_completed)
                await ws.send(json.dumps({
                    "type": "student_login_update",
                    "student_name": "",
                    "matricula": "",
                    "is_logged_in": False
                }))

            elif action == "bypass_student_login":
                # Libera o aluno remotamente sem exigir matrícula
                current_student_data["is_logged_in"] = True
                if not current_student_data["student_name"]:
                    current_student_data["student_name"] = USERNAME
                    current_student_data["matricula"] = "Liberado"
                ui_manager.trigger_bypass_login()
                await ws.send(json.dumps({
                    "type": "student_login_update",
                    "student_name": current_student_data["student_name"],
                    "matricula": current_student_data["matricula"],
                    "is_logged_in": True
                }))

        except websockets.ConnectionClosed:
            break
        except Exception as e:
            print(f"[Erro comando]: {e}")

MAIN_LOOP = {"loop": None}
# Conexão ativa com o professor. Callbacks de login usam esta referência (e não a conexão
# de quando a tela foi aberta), senão o aviso de login se perdia após uma reconexão.
CURRENT_WS = {"ws": None}


def _desktop_dir() -> str:
    home = os.path.expanduser("~")
    for name in ("Desktop", "Área de Trabalho", "Downloads"):
        path = os.path.join(home, name)
        if os.path.isdir(path):
            return path
    return APP_DIR


def save_received_file(filename: str, file_b64: str) -> str:
    file_bytes = base64.b64decode(file_b64)
    save_path = os.path.join(_desktop_dir(), filename)
    base, ext = os.path.splitext(save_path)
    n = 1
    while os.path.exists(save_path):  # não sobrescreve arquivos do aluno
        save_path = f"{base} ({n}){ext}"
        n += 1
    with open(save_path, "wb") as f:
        f.write(file_bytes)
    return save_path


def on_login_completed(name, mat, turma=""):
    current_student_data["student_name"] = name
    current_student_data["matricula"] = mat
    current_student_data["turma"] = turma
    current_student_data["is_logged_in"] = True
    print(f"[GESTORLAB] Aluno autenticado: {name} ({mat} - {turma})")

    # Sem conexão agora, os dados ficam guardados e vão no próximo "register".
    send_to_server({"type": "student_login_update", "student_name": name, "matricula": mat, "is_logged_in": True})


def send_to_server(payload: dict) -> None:
    """Envia ao professor a partir de qualquer thread (Tkinter, vigia de regras...)."""
    try:
        loop = MAIN_LOOP["loop"]
        ws_instance = CURRENT_WS["ws"]
        if loop and ws_instance:
            asyncio.run_coroutine_threadsafe(ws_instance.send(json.dumps(payload)), loop)
    except Exception as e:
        print(f"[Erro ao enviar ao professor]: {e}")


# ==========================================
# Regras do professor: programas e sites bloqueados
# ==========================================
RULES_PATH = os.path.join(DATA_DIR, "regras.json")
RULES = {"enabled": False, "programs": set(), "sites": []}
PROTECTED_PROGRAMS = {
    "explorer.exe", "svchost.exe", "csrss.exe", "winlogon.exe", "wininit.exe", "lsass.exe", "services.exe",
    "smss.exe", "dwm.exe", "taskmgr.exe", "python.exe", "pythonw.exe", "gestorlab aluno.exe", "system",
    "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "conhost.exe",
}
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "opera_gx.exe", "brave.exe",
            "vivaldi.exe", "iexplore.exe", "yandex.exe"}
RULES_CHECK_SECONDS = 1.5
REPORT_COOLDOWN_SECONDS = 30

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
VK_CONTROL, VK_W = 0x11, 0x57


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


# Tipos de retorno explícitos: o padrão (int de 32 bits) cortaria HANDLEs no Python 64 bits.
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
user32.GetForegroundWindow.restype = wintypes.HWND


def apply_rules(data: dict, persist: bool = False) -> None:
    programs = {str(p).strip().lower() for p in data.get("programs", []) if str(p).strip()}
    RULES["programs"] = programs - PROTECTED_PROGRAMS
    RULES["sites"] = [str(s).strip().lower() for s in data.get("sites", []) if len(str(s).strip()) >= 3]
    RULES["enabled"] = bool(data.get("enabled"))
    if persist:
        # Guardadas em disco: valem mesmo se o agente reiniciar sem conseguir falar com o professor.
        try:
            with open(RULES_PATH, "w", encoding="utf-8") as f:
                json.dump({"enabled": RULES["enabled"], "programs": sorted(RULES["programs"]),
                           "sites": RULES["sites"]}, f, ensure_ascii=False)
        except OSError as e:
            print(f"[Regras] Não foi possível gravar: {e}")


def load_saved_rules() -> None:
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            apply_rules(json.load(f))
    except (OSError, ValueError):
        pass


def list_processes():
    """[(pid, nome.exe)] via Toolhelp32 (sem chamar tasklist a cada segundo)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    result = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            result.append((entry.th32ProcessID, entry.szExeFile))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return result


def terminate_process(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def foreground_window():
    """(título, nome do processo) da janela em primeiro plano."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return buf.value, process_name(pid.value)


def blocked_site_in_title(title: str):
    lowered = title.lower()
    for word in RULES["sites"]:
        if word in lowered:
            return word
    return None


def close_active_tab():
    """Ctrl+W na janela do navegador em primeiro plano (fecha só a aba do site bloqueado)."""
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_W, 0, 0, 0)
    user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


_last_reports = {}


def report_violation(kind: str, detail: str) -> None:
    key = (kind, detail.lower())
    now = time.monotonic()
    if now - _last_reports.get(key, -REPORT_COOLDOWN_SECONDS) < REPORT_COOLDOWN_SECONDS:
        return   # não inunda o professor (nem o aluno) com o mesmo aviso
    _last_reports[key] = now
    what = "O programa" if kind == "programa" else "O site"
    ui_manager.trigger_toast("⛔ Bloqueado pelo professor", f"{what} '{detail}' não pode ser usado na aula.")
    send_to_server({"type": "rule_violation", "kind": kind, "detail": detail})


def enforce_rules_once() -> None:
    if not RULES["enabled"]:
        return
    if RULES["programs"]:
        own_pid = os.getpid()
        for pid, name in list_processes():
            if pid != own_pid and name.lower() in RULES["programs"] and terminate_process(pid):
                print(f"[Regras] Programa bloqueado encerrado: {name} ({pid})")
                report_violation("programa", name)
    if RULES["sites"]:
        title, proc = foreground_window()
        if proc in BROWSERS:
            word = blocked_site_in_title(title)
            if word:
                print(f"[Regras] Site bloqueado ({word}): {title}")
                close_active_tab()
                report_violation("site", word)
                time.sleep(1.0)   # dá tempo da aba fechar antes de olhar de novo


def rules_worker() -> None:
    while True:
        try:
            enforce_rules_once()
        except Exception as e:
            print(f"[Regras] Erro: {e}")
        time.sleep(RULES_CHECK_SECONDS)

async def stream_screen(ws):
    sct = mss.mss()
    capture_fail_count = 0
    try:
        while True:
            try:
                if stream_settings.get("paused"):
                    await asyncio.sleep(0.5)
                    continue
                curr_interval = stream_settings.get("interval", 0.5)
                curr_scale = stream_settings.get("scale", 0.4)
                curr_quality = stream_settings.get("quality", 45)

                try:
                    frame_data = capture_screen_base64(sct, scale=curr_scale, quality=curr_quality)
                    capture_fail_count = 0
                except Exception as e:
                    capture_fail_count += 1
                    frame_data = None
                    if capture_fail_count == 1:
                        print(f"[Captura de tela falhou]: {e}")
                    if capture_fail_count % 3 == 0:
                        # Recria o mss (contexto gráfico pode ter ficado inválido).
                        try:
                            sct.close()
                        except Exception:
                            pass
                        try:
                            sct = mss.mss()
                        except Exception:
                            pass
                    await asyncio.sleep(1.0)

                if frame_data:
                    payload = {
                        "type": "screen_frame",
                        "data": frame_data
                    }
                    await asyncio.wait_for(ws.send(json.dumps(payload)), timeout=2.0)
                await asyncio.sleep(curr_interval)
            except websockets.ConnectionClosed:
                break
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"[Erro no envio de tela]: {e}")
                await asyncio.sleep(0.5)

    except websockets.ConnectionClosed:
        pass
    finally:
        try:
            sct.close()
        except Exception:
            pass

async def run_client():
    MAIN_LOOP["loop"] = asyncio.get_running_loop()
    ensure_startup_persistence()
    # Se o agente caiu com a tela bloqueada, o Gerenciador de Tarefas ficaria desativado.
    set_task_manager_disabled(False)
    configured_host = CONFIG.get("server_host", "auto")
    configured_port = CONFIG.get("server_port", 8000)

    print(f"\n=======================================================")
    print(f"  [GESTORLAB AGENT] Computador: {HOSTNAME} ({USERNAME})")
    print(f"  Modo de Conexao: '{configured_host}' (Porta: {configured_port})")
    print(f"=======================================================\n")

    load_saved_rules()
    threading.Thread(target=rules_worker, daemon=True).start()

    # Inicia a tela de bloqueio / login do aluno se configurado
    if CONFIG.get("require_student_login", True) and not current_student_data["is_logged_in"]:
        ui_manager.trigger_student_login(on_login_completed)

    failures = 0   # tentativas seguidas sem conexão: aumenta a espera para não sobrecarregar o servidor

    def backoff() -> float:
        return min(30.0, 2.0 * (2 ** min(failures, 4))) + random.uniform(0, 2.0)

    while True:
        target_ip = None
        target_port = configured_port

        if not configured_host or str(configured_host).lower() in ["auto", ""]:
            print("[Auto-Descoberta] Buscando servidor do professor na rede escolar...")
            discovered_ip, discovered_port = await asyncio.to_thread(discover_server, 8001, 1.5)
            if discovered_ip:
                print(f"[Auto-Descoberta] Servidor do professor localizado: {discovered_ip}:{discovered_port}")
                target_ip = discovered_ip
                target_port = discovered_port
                ACTIVE_SERVER["ip"] = target_ip
                ACTIVE_SERVER["port"] = target_port
            else:
                failures += 1
                wait = backoff()
                print(f"[Auto-Descoberta] Servidor do professor nao respondeu. Nova tentativa em {wait:.0f}s...")
                await asyncio.sleep(wait)
                continue
        else:
            target_ip = configured_host
            ACTIVE_SERVER["ip"] = target_ip
            ACTIVE_SERVER["port"] = target_port

        ws_url = f"ws://{target_ip}:{target_port}/ws/client"
        print(f"Tentando conectar ao professor em: {ws_url}")

        try:
            async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
                CURRENT_WS["ws"] = ws
                register_payload = {
                    "type": "register",
                    "hostname": HOSTNAME,
                    "username": USERNAME,
                    "student_name": current_student_data["student_name"],
                    "matricula": current_student_data["matricula"],
                    "is_student_logged_in": current_student_data["is_logged_in"],
                    "is_locked": ui_manager.is_locked,
                    "lock_remaining": ui_manager.lock_remaining(),
                    "turma": current_student_data.get("turma", ""),
                    "agent_key": CONFIG.get("agent_key", ""),
                    "os": windows_name(),
                }
                await ws.send(json.dumps(register_payload))
                
                ack_raw = await ws.recv()
                print(f"[Conectado e registrado com sucesso no painel do professor!]")
                failures = 0

                cmd_task = asyncio.create_task(handle_commands(ws))
                screen_task = asyncio.create_task(stream_screen(ws))

                done, pending = await asyncio.wait(
                    [cmd_task, screen_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

        except Exception as e:
            failures += 1
            wait = backoff()
            print(f"[Aguardando conexao com o professor...] ({e}) Nova tentativa em {wait:.0f}s")
            await asyncio.sleep(wait)
        else:
            # Conexão que durou e caiu: reconecta logo (com um pequeno atraso aleatório).
            await asyncio.sleep(random.uniform(0.5, 2.5))
        finally:
            CURRENT_WS["ws"] = None


def windows_name() -> str:
    try:
        build = sys.getwindowsversion().build
        return "Windows 11" if build >= 22000 else "Windows 10"
    except Exception:
        return "Windows"

if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        print("\nAgente encerrado.")
