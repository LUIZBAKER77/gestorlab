"""Caminhos e configuração do servidor.

As configurações ficam em server_config.json, ao lado do executável (ou deste
arquivo, em modo desenvolvimento). O arquivo é criado na primeira execução.
"""
import json
import os
import secrets
import sys

FROZEN = getattr(sys, "frozen", False)

# Pasta gravável: onde ficam o banco de dados e o server_config.json.
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))

# Pasta dos arquivos empacotados (static/). Em exe "onefile" é um diretório temporário.
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)

STATIC_DIR = os.path.join(RESOURCE_DIR, "static")
if not os.path.isdir(STATIC_DIR):
    STATIC_DIR = os.path.join(APP_DIR, "static")

# Dados do usuário (banco, configuração, log). O lançador define GESTORLAB_DATA
# para uma pasta "dados" ao lado do .exe, assim atualizar o programa não apaga nada.
DATA_DIR = os.environ.get("GESTORLAB_DATA") or APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(DATA_DIR, "server_config.json")
DB_PATH = os.path.join(DATA_DIR, "gestorlab.db")

# Sem console (pythonw.exe), sys.stdout é None e o uvicorn falha ao logar: grava em arquivo.
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(DATA_DIR, "servidor.log"), "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

DEFAULT_PASSWORD = "padrao#jf"

_DEFAULTS = {
    "admin_password": DEFAULT_PASSWORD,
    "secret_key": "",          # gerada automaticamente na primeira execução
    "agent_key": "",           # opcional: se preenchida, os agentes precisam apresentá-la
    "port": 8000,
    "discovery_port": 8001,
    "open_browser": True,
    "max_upload_mb": 40,
    # Regras de uso aplicadas pelos agentes (editáveis na aba "Regras" do painel).
    "rules_enabled": False,
    "blocked_programs": [],   # nomes de executáveis, ex.: "RobloxPlayerBeta.exe"
    "blocked_sites": [],      # palavras procuradas no título da janela do navegador, ex.: "YouTube"
}


def _load() -> dict:
    cfg = dict(_DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, ValueError) as e:
            print(f"[GESTORLAB] server_config.json inválido, usando padrões: {e}")

    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> bool:
    """Grava a configuração (arquivo temporário + troca, para não corromper se faltar luz)."""
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
        return True
    except OSError as e:
        print(f"[GESTORLAB] Não foi possível gravar server_config.json: {e}")
        return False


CONFIG = _load()
