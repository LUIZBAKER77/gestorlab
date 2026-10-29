import asyncio
import base64
import csv
import io
import json
import os
import socket
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlsplit
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import (Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import auth
import database
from config import CONFIG, DEFAULT_PASSWORD, STATIC_DIR, save_config

PORT = int(CONFIG["port"])
DISCOVERY_PORT = int(CONFIG["discovery_port"])
MAX_UPLOAD_BYTES = int(CONFIG["max_upload_mb"]) * 1024 * 1024

# Comandos que o painel pode repassar aos agentes dos alunos.
ALLOWED_ACTIONS = {
    "lock", "unlock", "message", "set_stream_settings", "remote_input",
    "power", "student_logout", "bypass_student_login", "open_url",
}
ATTENDANCE_HEARTBEAT_SECONDS = 60
MAX_LOCK_SECONDS = 4 * 3600
# Nunca fechados pelo agente, mesmo se alguém os colocar na lista de bloqueio.
PROTECTED_PROGRAMS = {
    "explorer.exe", "svchost.exe", "csrss.exe", "winlogon.exe", "wininit.exe", "lsass.exe", "services.exe",
    "smss.exe", "dwm.exe", "taskmgr.exe", "python.exe", "pythonw.exe", "gestorlab aluno.exe",
    "gestorlab professor.exe", "system", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "conhost.exe",
}


# ==========================================
# Modelos de requisição
# ==========================================
class LoginRequest(BaseModel):
    password: str = Field(max_length=200)
    remember: bool = True


class StudentCreateRequest(BaseModel):
    name: str = Field(max_length=150)
    matricula: str = Field(max_length=40)
    turma: str = Field("", max_length=60)
    password: str = Field(max_length=100)


class StudentUpdateRequest(BaseModel):
    name: str = Field(max_length=150)
    turma: str = Field("", max_length=60)
    matricula: Optional[str] = Field(None, max_length=40)
    password: Optional[str] = Field(None, max_length=100)


class StudentBulkDeleteRequest(BaseModel):
    ids: List[int]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class RulesRequest(BaseModel):
    enabled: bool = False
    programs: List[str] = Field(default_factory=list, max_length=200)
    sites: List[str] = Field(default_factory=list, max_length=200)


class StudentVerifyLoginRequest(BaseModel):
    matricula: str = Field(max_length=40)
    password: str = Field(max_length=100)


# ==========================================
# Estado em memória
# ==========================================
connected_clients: Dict[str, Dict[str, Any]] = {}
dashboard_websockets = set()
dashboard_busy = set()
_background_tasks = set()

login_limiter = auth.RateLimiter(max_fails=5, window=60)
student_limiter = auth.RateLimiter(max_fails=10, window=60)


def get_local_ips() -> List[str]:
    """IPs desta máquina, com o da rede principal primeiro.

    A ordem do gethostbyname_ex é arbitrária: com VirtualBox/Hyper-V/VPN instalados, o
    painel mostrava o IP do adaptador virtual (ex.: 192.168.56.1) em vez do da escola.
    """
    ips = []
    try:
        # "Conectar" UDP não envia pacotes: só pergunta ao Windows qual interface tem a rota padrão.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        if not ip.startswith(("127.", "169.254.", "0.")):
            ips.append(ip)
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith(("127.", "169.254.")) and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


def start_udp_discovery() -> None:
    """Responde aos pings dos agentes para que achem o servidor sem digitar IP."""
    def worker():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DISCOVERY_PORT))
        except OSError as e:
            print(f"[GESTORLAB] Descoberta automática indisponível (UDP {DISCOVERY_PORT}): {e}")
            sock.close()
            return
        print(f"[GESTORLAB] Descoberta automática ativa na porta UDP {DISCOVERY_PORT}")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data == b"GESTORLAB_DISCOVERY_PING":
                    sock.sendto(f"GESTORLAB_SERVER:{PORT}".encode("utf-8"), addr)
            except OSError:
                # No Windows, recvfrom pode falhar com WSAECONNRESET; segue ouvindo.
                time.sleep(0.2)

    threading.Thread(target=worker, daemon=True).start()


async def attendance_heartbeat() -> None:
    """Registra periodicamente que as sessões abertas seguem ativas.

    Se o computador do professor for desligado sem fechar o programa, a presença é
    encerrada no último sinal de vida (antes ficava com duração zero).
    """
    while True:
        await asyncio.sleep(ATTENDANCE_HEARTBEAT_SECONDS)
        try:
            await asyncio.to_thread(database.touch_open_attendance)
        except Exception as e:
            print(f"[GESTORLAB] Erro ao atualizar presença: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    start_udp_discovery()
    heartbeat = asyncio.create_task(attendance_heartbeat())
    if CONFIG["admin_password"] == DEFAULT_PASSWORD:
        print("[GESTORLAB] AVISO: a senha do painel ainda é a padrão. Troque-a em Configurações, no painel.")
    yield
    heartbeat.cancel()


app = FastAPI(title="GestorLab Server", lifespan=lifespan)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


# ==========================================
# Comunicação com dashboards e agentes
# ==========================================
async def _send(ws: WebSocket, text: str, timeout: float) -> bool:
    try:
        await asyncio.wait_for(ws.send_text(text), timeout=timeout)
        return True
    except Exception:
        return False


async def broadcast_to_dashboards(message: dict) -> None:
    sockets = list(dashboard_websockets)
    if not sockets:
        return
    text = json.dumps(message)
    results = await asyncio.gather(*(_send(ws, text, 1.0) for ws in sockets))
    for ws, ok in zip(sockets, results):
        if not ok:
            dashboard_websockets.discard(ws)
            dashboard_busy.discard(ws)


def broadcast_frame_nonblocking(client_id: str, frame_data: str) -> None:
    if not dashboard_websockets:
        return
    text = json.dumps({"type": "screen_frame", "client_id": client_id, "data": frame_data})
    for ws in list(dashboard_websockets):
        if ws in dashboard_busy:
            continue  # o painel ainda processa o quadro anterior: descarta este
        task = asyncio.create_task(_send_frame_to_dashboard(ws, text))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def _send_frame_to_dashboard(ws: WebSocket, text: str) -> None:
    dashboard_busy.add(ws)
    try:
        if not await _send(ws, text, 0.35):
            dashboard_websockets.discard(ws)
    finally:
        dashboard_busy.discard(ws)


async def command_all_clients(action: str) -> None:
    """Envia um comando simples (sem alvo individual) a todos os agentes conectados."""
    text = json.dumps({"action": action})
    clients = list(connected_clients.values())
    if clients:
        await asyncio.gather(*(_send(c["ws"], text, 5.0) for c in clients))


def lock_remaining(info: dict) -> int:
    """Segundos até o timer liberar a tela (0 = sem timer). Relativo, para não depender do
    relógio do computador onde o painel está aberto."""
    until = info.get("lock_until")
    return max(0, int(until - time.time())) if until and info.get("is_locked") else 0


def public_info(info: dict) -> dict:
    return {**info, "lock_remaining": lock_remaining(info)}


def client_summary(cid: str, cdata: Dict[str, Any]) -> dict:
    return {"id": cid, "info": public_info(cdata["info"]), "latest_frame": cdata.get("latest_frame")}


def resolve_targets(target: Any) -> List[Dict[str, Any]]:
    """'all', 'turma:<nome>' (alunos logados daquela turma) ou o id de um computador."""
    if target == "all":
        return list(connected_clients.values())
    if isinstance(target, str) and target.startswith("turma:"):
        turma = target[len("turma:"):].strip().casefold()
        return [c for c in connected_clients.values() if (c["info"].get("turma") or "").strip().casefold() == turma]
    if target in connected_clients:
        return [connected_clients[target]]
    return []


def rules_payload() -> dict:
    return {
        "action": "set_rules",
        "enabled": bool(CONFIG.get("rules_enabled")),
        "programs": list(CONFIG.get("blocked_programs") or []),
        "sites": list(CONFIG.get("blocked_sites") or []),
    }


# ==========================================
# Autenticação do professor
# ==========================================
@app.post("/api/login")
async def api_login(req: LoginRequest, request: Request):
    ip = client_ip(request)
    if login_limiter.blocked(ip):
        return JSONResponse(status_code=429, content={"success": False, "error": "Muitas tentativas. Aguarde 1 minuto."})
    if auth.check_admin_password(req.password):
        login_limiter.reset(ip)
        return {"success": True, "token": auth.create_access_token(remember=req.remember)}
    login_limiter.fail(ip)
    return JSONResponse(status_code=401, content={"success": False, "error": "Senha incorreta"})


@app.get("/api/verify-auth")
async def api_verify_auth(request: Request, token: Optional[str] = Query(None)):
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if auth.verify_token(token):
        return {"valid": True}
    return JSONResponse(status_code=401, content={"valid": False})


@app.get("/api/server-info", dependencies=[Depends(auth.require_auth)])
async def get_server_info():
    ips = get_local_ips()
    return {
        "local_ip": ips[0],
        "all_ips": ips,
        "port": PORT,
        "discovery_port": DISCOVERY_PORT,
        "total_clients": len(connected_clients),
        "clients": list(connected_clients.keys()),
        "default_password": CONFIG["admin_password"] == DEFAULT_PASSWORD,
        "max_upload_mb": CONFIG["max_upload_mb"],
    }


@app.post("/api/admin/password", dependencies=[Depends(auth.require_auth)])
async def change_admin_password(req: ChangePasswordRequest, request: Request):
    ip = client_ip(request)
    if login_limiter.blocked(ip):
        return JSONResponse(status_code=429, content={"success": False, "error": "Muitas tentativas. Aguarde 1 minuto."})
    if not auth.check_admin_password(req.current_password):
        login_limiter.fail(ip)
        return JSONResponse(status_code=400, content={"success": False, "error": "A senha atual está incorreta."})
    new = req.new_password.strip()
    if len(new) < 6:
        return JSONResponse(status_code=400, content={"success": False, "error": "A nova senha precisa ter pelo menos 6 caracteres."})
    if new == CONFIG["admin_password"]:
        return JSONResponse(status_code=400, content={"success": False, "error": "A nova senha é igual à atual."})

    old = CONFIG["admin_password"]
    CONFIG["admin_password"] = new
    if not await asyncio.to_thread(save_config, CONFIG):
        CONFIG["admin_password"] = old
        return JSONResponse(status_code=500, content={"success": False, "error": "Não foi possível gravar a configuração."})
    login_limiter.reset(ip)
    print("[GESTORLAB] Senha do painel alterada; sessões anteriores foram encerradas.")
    # Painéis já abertos foram autorizados com a senha antiga: força a reconexão (quem não
    # tiver o token novo cai na tela de login).
    for ws in list(dashboard_websockets):
        try:
            await ws.close(code=4005, reason="Senha alterada")
        except Exception:
            pass
    # A senha faz parte da assinatura dos tokens: os antigos (outros navegadores) deixam de valer.
    return {"success": True, "token": auth.create_access_token(remember=True)}


# ==========================================
# Gestão de alunos (CRUD)
# ==========================================
def _db_result(ok: bool, res: Any, key: str):
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "error": res})
    return {"success": True, key: res}


@app.get("/api/students", dependencies=[Depends(auth.require_auth)])
async def get_students_api(q: Optional[str] = None):
    return {"success": True, "students": await asyncio.to_thread(database.list_students, q)}


@app.post("/api/students", dependencies=[Depends(auth.require_auth)])
async def create_student_api(req: StudentCreateRequest):
    ok, res = await asyncio.to_thread(database.create_student, req.name, req.matricula, req.turma, req.password)
    return _db_result(ok, res, "student")


@app.put("/api/students/{student_id}", dependencies=[Depends(auth.require_auth)])
async def update_student_api(student_id: int, req: StudentUpdateRequest):
    ok, res = await asyncio.to_thread(
        database.update_student, student_id, req.name, req.turma, req.matricula, req.password)
    return _db_result(ok, res, "message")


@app.delete("/api/students/{student_id}", dependencies=[Depends(auth.require_auth)])
async def delete_student_api(student_id: int):
    ok, res = await asyncio.to_thread(database.delete_student, student_id)
    return _db_result(ok, res, "message")


MAX_IMPORT_BYTES = 5 * 1024 * 1024


@app.post("/api/students/import", dependencies=[Depends(auth.require_auth)])
async def import_students_api(file: UploadFile = File(...), update_existing: bool = Form(False)):
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        return JSONResponse(status_code=413, content={"success": False, "error": "Planilha maior que 5 MB."})
    rows, error = database.parse_students_csv(raw)
    if error:
        return JSONResponse(status_code=400, content={"success": False, "error": error})
    result = await asyncio.to_thread(database.import_students, rows, update_existing)
    return {"success": True, **result}


def csv_response(header: List[str], rows: List[list], filename: str) -> Response:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content="﻿" + out.getvalue(),   # BOM: o Excel abre os acentos corretamente
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/students.csv", dependencies=[Depends(auth.require_auth)])
async def export_students_csv():
    students = await asyncio.to_thread(database.list_students)
    return csv_response(["Matrícula", "Nome", "Turma", "Cadastrado em"],
                        [[s["matricula"], s["name"], s["turma"], s["created_at"]] for s in students],
                        "alunos.csv")


@app.post("/api/students/bulk-delete", dependencies=[Depends(auth.require_auth)])
async def bulk_delete_students_api(req: StudentBulkDeleteRequest):
    ok, res = await asyncio.to_thread(database.bulk_delete_students, req.ids)
    return _db_result(ok, res, "message")


@app.post("/api/student/verify-login")
async def verify_student_login_api(req: StudentVerifyLoginRequest, request: Request):
    """Chamado pelo agente do aluno (sem login de professor)."""
    if not auth.check_agent_key(request.headers.get("x-agent-key")):
        return JSONResponse(status_code=403, content={"success": False, "error": "Agente não autorizado."})
    ip = client_ip(request)
    if student_limiter.blocked(ip):
        return JSONResponse(status_code=429, content={"success": False, "error": "Muitas tentativas. Aguarde 1 minuto."})
    ok, res = await asyncio.to_thread(database.verify_student_login, req.matricula, req.password)
    if not ok:
        student_limiter.fail(ip)
        return JSONResponse(status_code=401, content={"success": False, "error": res})
    student_limiter.reset(ip)
    return {"success": True, "student": res}


# ==========================================
# Presença
# ==========================================
@app.get("/api/attendance", dependencies=[Depends(auth.require_auth)])
async def attendance_api(start: Optional[str] = None, end: Optional[str] = None, q: Optional[str] = None):
    rows = await asyncio.to_thread(database.list_attendance, start, end, q)
    return {"success": True, "records": rows}


def _duration_minutes(login_at: str, logout_at: Optional[str]) -> str:
    try:
        start = datetime.strptime(login_at, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(logout_at, "%Y-%m-%d %H:%M:%S") if logout_at else datetime.now()
        return str(max(0, round((end - start).total_seconds() / 60)))
    except (TypeError, ValueError):
        return ""


@app.get("/api/attendance.csv", dependencies=[Depends(auth.require_auth)])
async def attendance_csv(start: Optional[str] = None, end: Optional[str] = None, q: Optional[str] = None):
    rows = await asyncio.to_thread(database.list_attendance, start, end, q, 100000)
    return csv_response(
        ["Matrícula", "Aluno", "Turma", "Computador", "IP", "Entrada", "Saída", "Duração (min)"],
        [[r["matricula"], r["student_name"], r["turma"], r["hostname"], r["ip"], r["login_at"],
          r["logout_at"] or "", _duration_minutes(r["login_at"], r["logout_at"])] for r in rows],
        "presenca.csv",
    )


# ==========================================
# Regras de uso (programas e sites bloqueados)
# ==========================================
def _clean_programs(items: List[str]) -> List[str]:
    out = []
    for raw in items:
        name = os.path.basename(str(raw).strip().strip('"').replace("\\", "/"))[:100]
        if not name:
            continue
        if "." not in name:
            name += ".exe"
        if name.lower() not in PROTECTED_PROGRAMS and name.lower() not in (p.lower() for p in out):
            out.append(name)
    return out


def _clean_sites(items: List[str]) -> List[str]:
    out = []
    for raw in items:
        word = str(raw).strip()[:100]
        # Endereço colado ("https://www.youtube.com/...") vira a palavra principal ("youtube").
        host = urlsplit(word if "://" in word else f"//{word}").hostname or ""
        if "." in host:
            parts = [p for p in host.split(".") if p not in ("www", "m", "com", "br", "org", "net", "gov", "edu")]
            word = max(parts, key=len) if parts else host
        if len(word) >= 3 and word.lower() not in (w.lower() for w in out):
            out.append(word)
    return out


@app.get("/api/rules", dependencies=[Depends(auth.require_auth)])
async def get_rules():
    payload = rules_payload()
    return {"success": True, "enabled": payload["enabled"], "programs": payload["programs"], "sites": payload["sites"]}


@app.put("/api/rules", dependencies=[Depends(auth.require_auth)])
async def update_rules(req: RulesRequest):
    previous = {k: CONFIG.get(k) for k in ("rules_enabled", "blocked_programs", "blocked_sites")}
    CONFIG["rules_enabled"] = req.enabled
    CONFIG["blocked_programs"] = _clean_programs(req.programs)
    CONFIG["blocked_sites"] = _clean_sites(req.sites)
    if not await asyncio.to_thread(save_config, CONFIG):
        CONFIG.update(previous)
        return JSONResponse(status_code=500, content={"success": False, "error": "Não foi possível gravar a configuração."})
    payload = rules_payload()
    text = json.dumps(payload)
    clients = list(connected_clients.values())
    sent = await asyncio.gather(*(_send(c["ws"], text, 5.0) for c in clients)) if clients else []
    return {"success": True, "enabled": payload["enabled"], "programs": payload["programs"],
            "sites": payload["sites"], "sent_count": sum(sent)}


@app.get("/api/events", dependencies=[Depends(auth.require_auth)])
async def events_api():
    return {"success": True, "events": await asyncio.to_thread(database.list_events)}


# ==========================================
# Envio de arquivos
# ==========================================
@app.post("/api/file-transfer", dependencies=[Depends(auth.require_auth)])
async def api_file_transfer(file: UploadFile = File(...), target: str = Form("all")):
    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Arquivo maior que o limite de {CONFIG['max_upload_mb']} MB.")

    filename = os.path.basename((file.filename or "arquivo").replace("\\", "/")) or "arquivo"
    payload = json.dumps({
        "action": "receive_file",
        "filename": filename,
        "size": len(file_bytes),
        "data": base64.b64encode(file_bytes).decode("ascii"),
    })

    targets = resolve_targets(target)
    if not targets and target != "all":
        raise HTTPException(status_code=404, detail="Nenhum computador conectado para este destino.")

    results = await asyncio.gather(*(_send(c["ws"], payload, 30.0) for c in targets))
    return {"success": True, "filename": filename, "sent_count": sum(results)}


# ==========================================
# WebSocket do painel do professor
# ==========================================
@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket, token: Optional[str] = Query(None)):
    await websocket.accept()
    if not auth.verify_token(token):
        await websocket.close(code=4001, reason="Não autorizado")
        return

    first_dashboard = not dashboard_websockets
    dashboard_websockets.add(websocket)
    if first_dashboard:
        await command_all_clients("stream_resume")   # alguém está olhando: agentes voltam a enviar telas
    ips = get_local_ips()
    await websocket.send_text(json.dumps({
        "type": "init",
        "server_ip": ips[0],
        "server_port": PORT,
        "all_ips": ips,
        "clients": [client_summary(cid, c) for cid, c in connected_clients.items()],
    }))

    try:
        while True:
            try:
                data = json.loads(await websocket.receive_text())
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("action") not in ALLOWED_ACTIONS:
                continue
            await dispatch_command(data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[GESTORLAB] Erro no painel: {e}")
    finally:
        dashboard_websockets.discard(websocket)
        dashboard_busy.discard(websocket)
        if not dashboard_websockets:
            # Ninguém olhando: volta à qualidade padrão e pausa o envio de telas (poupa a rede).
            await command_all_clients("reset_stream")
            await command_all_clients("stream_pause")


async def dispatch_command(data: dict) -> None:
    action = data["action"]
    target = data.get("target")
    if action == "open_url":
        url = str(data.get("url", "")).strip()[:2000]
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            return   # só sites: nada de file://, programas etc.
        data = {"action": "open_url", "target": target, "url": url}
    duration = 0
    if action == "lock":
        # Timer opcional: o próprio agente libera a tela quando o tempo acaba.
        try:
            duration = max(0, min(int(float(data.get("duration") or 0)), MAX_LOCK_SECONDS))
        except (TypeError, ValueError):
            duration = 0
        data = {**data, "duration": duration}
    targets = resolve_targets(target)
    if not targets:
        return

    text = json.dumps(data)
    results = await asyncio.gather(*(_send(c["ws"], text, 5.0) for c in targets))

    if action in ("lock", "unlock"):
        lock_until = time.time() + duration if (action == "lock" and duration) else None
        for c, ok in zip(targets, results):
            if ok:
                c["info"]["is_locked"] = (action == "lock")
                c["info"]["lock_until"] = lock_until
                await broadcast_to_dashboards(status_message(c["info"]))


def status_message(info: dict) -> dict:
    return {"type": "status_update", "client_id": info["id"], "is_locked": info.get("is_locked", False),
            "lock_remaining": lock_remaining(info)}


# ==========================================
# WebSocket dos agentes (alunos)
# ==========================================
def _set_student(client_id: str, name: str, matricula: str, logged_in: bool) -> dict:
    info = connected_clients[client_id]["info"]
    info["student_name"] = name
    info["matricula"] = matricula
    info["is_student_logged_in"] = logged_in
    return {
        "type": "student_login_update",
        "client_id": client_id,
        "student_name": name,
        "matricula": matricula,
        "is_student_logged_in": logged_in,
    }


def _remaining_to_deadline(value: Any) -> Optional[float]:
    try:
        seconds = float(value or 0)
    except (TypeError, ValueError):
        return None
    return time.time() + min(seconds, MAX_LOCK_SECONDS) if seconds > 0 else None


@app.websocket("/ws/client")
async def websocket_client(websocket: WebSocket):
    await websocket.accept()
    client_id = None
    try:
        init = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
        if not isinstance(init, dict) or init.get("type") != "register":
            await websocket.close(code=4002, reason="Registro esperado")
            return
        if not auth.check_agent_key(init.get("agent_key")):
            await websocket.close(code=4003, reason="Agente não autorizado")
            return

        host = websocket.client.host if websocket.client else "?"
        client_id = str(init.get("id") or f"{init.get('hostname', 'pc')}-{host}")[:120]
        info = {
            "id": client_id,
            "hostname": str(init.get("hostname", "Desconhecido"))[:100],
            "username": str(init.get("username", "Aluno"))[:100],
            "student_name": str(init.get("student_name", ""))[:150],
            "matricula": str(init.get("matricula", ""))[:40],
            "is_student_logged_in": bool(init.get("is_student_logged_in", False)),
            "ip": host,
            "os": str(init.get("os", "Windows 10"))[:60],
            "is_locked": bool(init.get("is_locked", False)),
            "lock_until": _remaining_to_deadline(init.get("lock_remaining")),
            "turma": str(init.get("turma", ""))[:60],
        }

        old = connected_clients.get(client_id)
        connected_clients[client_id] = {"ws": websocket, "info": info, "latest_frame": None}
        if old:
            try:
                await old["ws"].close()
            except Exception:
                pass
        print(f"[GESTORLAB] Aluno conectado: {client_id} ({info['student_name'] or 'sem login'})")
        if info["is_student_logged_in"] and info["matricula"] and info["matricula"] != "Liberado":
            # Reconexão de um aluno já identificado: reabre a sessão de presença.
            info["turma"] = await asyncio.to_thread(database.record_attendance, info["matricula"],
                                                    info["student_name"], info["hostname"], host) or info["turma"]

        await broadcast_to_dashboards({"type": "client_connected", "client": public_info(info)})
        await websocket.send_text(json.dumps({"type": "registered", "id": client_id}))
        await websocket.send_text(json.dumps(rules_payload()))
        if not dashboard_websockets:
            await websocket.send_text(json.dumps({"action": "stream_pause"}))

        while True:
            try:
                msg = json.loads(await websocket.receive_text())
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            await handle_client_message(websocket, client_id, msg)

    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception as e:
        print(f"[GESTORLAB] Erro no cliente {client_id}: {e}")
    finally:
        # Só remove se esta conexão ainda é a registrada (o agente pode ter reconectado).
        current = connected_clients.get(client_id) if client_id else None
        if current and current["ws"] is websocket:
            del connected_clients[client_id]
            print(f"[GESTORLAB] Aluno desconectado: {client_id}")
            await asyncio.to_thread(database.close_attendance, current["info"]["hostname"])
            await broadcast_to_dashboards({"type": "client_disconnected", "client_id": client_id})


async def handle_client_message(websocket: WebSocket, client_id: str, msg: dict) -> None:
    current = connected_clients.get(client_id)
    if not current or current["ws"] is not websocket:
        return
    msg_type = msg.get("type")

    if msg_type == "screen_frame":
        frame = msg.get("data")
        if isinstance(frame, str):
            current["latest_frame"] = frame
            broadcast_frame_nonblocking(client_id, frame)

    elif msg_type == "status_ack":
        info = current["info"]
        info["is_locked"] = bool(msg.get("is_locked", False))
        # O agente informa quanto falta do timer (ou 0); desbloqueado nunca tem prazo.
        info["lock_until"] = _remaining_to_deadline(msg.get("lock_remaining")) if info["is_locked"] else None
        await broadcast_to_dashboards(status_message(info))

    elif msg_type == "student_login_update":
        update = _set_student(client_id, str(msg.get("student_name", ""))[:150],
                              str(msg.get("matricula", ""))[:40], bool(msg.get("is_logged_in", True)))
        print(f"[GESTORLAB] Login atualizado: {client_id} -> {update['student_name']} ({update['matricula']})")
        info = current["info"]
        turma = ""
        if update["is_student_logged_in"] and update["matricula"] and update["matricula"] != "Liberado":
            turma = await asyncio.to_thread(database.record_attendance, update["matricula"], update["student_name"],
                                            info["hostname"], info["ip"])
        elif not update["is_student_logged_in"]:
            await asyncio.to_thread(database.close_attendance, info["hostname"])
        info["turma"] = update["turma"] = turma
        await broadcast_to_dashboards(update)

    elif msg_type == "rule_violation":
        info = current["info"]
        kind = "site" if msg.get("kind") == "site" else "programa"
        detail = str(msg.get("detail", ""))[:200]
        await asyncio.to_thread(database.record_event, info["hostname"], info["student_name"], kind, detail)
        await broadcast_to_dashboards({"type": "rule_violation", "client_id": client_id, "hostname": info["hostname"],
                                       "student_name": info["student_name"], "kind": kind, "detail": detail})

    elif msg_type == "file_received_ack":
        await broadcast_to_dashboards({
            "type": "file_transfer_status",
            "client_id": client_id,
            "filename": msg.get("filename", ""),
            "status": msg.get("status", "ok"),
            "path": msg.get("path", ""),
        })


# ==========================================
# Arquivos estáticos
# ==========================================
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    # O lançador desativa a abertura do navegador quando o início é automático (login do Windows).
    if CONFIG.get("open_browser", True) and os.environ.get("GESTORLAB_BROWSER", "1") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    ip_list = ", ".join(f"http://{ip}:{PORT}" for ip in get_local_ips())
    print("\n=======================================================")
    print("  [GESTORLAB] SERVIDOR DO PROFESSOR EM EXECUÇÃO")
    print(f"  Acesse no seu navegador: http://localhost:{PORT}")
    print(f"  Ou na rede local:        {ip_list}")
    print(f"  Descoberta automática:   UDP porta {DISCOVERY_PORT}")
    print("=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
