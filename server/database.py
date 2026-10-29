import csv
import hashlib
import hmac
import re
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from config import CONFIG, DB_PATH, DEFAULT_PASSWORD

PBKDF2_ROUNDS = 100_000
PUBLIC_COLUMNS = "id, matricula, name, turma, created_at"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Abre uma conexão, faz commit/rollback e sempre fecha."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS).hex()
    return pwd_hash, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    pwd_hash, _ = hash_password(password, salt)
    return hmac.compare_digest(pwd_hash, stored_hash)


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                turma TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT NOT NULL,
                student_name TEXT NOT NULL,
                turma TEXT DEFAULT '',
                hostname TEXT NOT NULL,
                ip TEXT DEFAULT '',
                login_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
                logout_at TIMESTAMP,
                last_seen TIMESTAMP
            )
        """)
        # Bancos antigos não têm last_seen.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(attendance)")}
        if "last_seen" not in columns:
            conn.execute("ALTER TABLE attendance ADD COLUMN last_seen TIMESTAMP")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_login ON attendance(login_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
                hostname TEXT NOT NULL,
                student_name TEXT DEFAULT '',
                kind TEXT NOT NULL,
                detail TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_at ON events(at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                must_change INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                last_login TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
                user_email TEXT NOT NULL,
                user_name TEXT DEFAULT '',
                action TEXT NOT NULL,
                detail TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at)")
        # Sessões que ficaram abertas (servidor desligado) são encerradas no último sinal
        # de vida registrado, e não mais com duração zero.
        conn.execute("UPDATE attendance SET logout_at = COALESCE(last_seen, login_at) WHERE logout_at IS NULL")
        if conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0:
            pwd_hash, salt = hash_password("123456")
            conn.execute(
                "INSERT INTO students (matricula, name, turma, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
                ("2026001", "Aluno Exemplo", "Turma A", pwd_hash, salt),
            )
            print("[GESTORLAB DB] Banco criado com aluno modelo (Matrícula: 2026001 / Senha: 123456). Exclua-o depois.")
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            # Primeira execução: conta provisória "admin" com a senha do server_config.json.
            # Entre com ela, cadastre a equipe em Equipe e apague esta conta.
            pwd_hash, salt = hash_password(str(CONFIG["admin_password"]))
            conn.execute(
                "INSERT INTO users (email, name, password_hash, salt, role, must_change) VALUES (?, ?, ?, ?, 'admin', ?)",
                ("admin", "Administrador inicial", pwd_hash, salt, 1 if CONFIG["admin_password"] == DEFAULT_PASSWORD else 0))
            print("[GESTORLAB DB] Conta inicial criada: usuário 'admin' (senha do server_config.json).")


def list_students(query: Optional[str] = None) -> List[Dict[str, Any]]:
    with connect() as conn:
        if query and query.strip():
            q = f"%{query.strip()}%"
            rows = conn.execute(
                f"SELECT {PUBLIC_COLUMNS} FROM students "
                "WHERE matricula LIKE ? OR name LIKE ? OR turma LIKE ? ORDER BY name COLLATE NOCASE",
                (q, q, q),
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT {PUBLIC_COLUMNS} FROM students ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]


def get_student_by_matricula(matricula: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {PUBLIC_COLUMNS}, password_hash, salt FROM students WHERE matricula = ?",
            (matricula.strip(),),
        ).fetchone()
        return dict(row) if row else None


def create_student(name: str, matricula: str, turma: str, password: str) -> Tuple[bool, Any]:
    name, matricula, turma, password = name.strip(), matricula.strip(), turma.strip(), password.strip()
    if not name or not matricula or not password:
        return False, "Nome, matrícula e senha são obrigatórios."

    pwd_hash, salt = hash_password(password)
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO students (matricula, name, turma, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
                (matricula, name, turma, pwd_hash, salt),
            )
            return True, {"id": cur.lastrowid, "matricula": matricula, "name": name, "turma": turma}
    except sqlite3.IntegrityError:
        return False, f"A matrícula '{matricula}' já está cadastrada para outro aluno."
    except sqlite3.Error as e:
        return False, str(e)


def update_student(student_id: int, name: str, turma: str, matricula: Optional[str] = None,
                   new_password: Optional[str] = None) -> Tuple[bool, Any]:
    name, turma = name.strip(), turma.strip()
    if not name:
        return False, "O nome do aluno não pode ser vazio."

    fields = {"name": name, "turma": turma}
    if matricula and matricula.strip():
        fields["matricula"] = matricula.strip()
    if new_password and new_password.strip():
        fields["password_hash"], fields["salt"] = hash_password(new_password.strip())

    assignments = ", ".join(f"{col} = ?" for col in fields)
    try:
        with connect() as conn:
            cur = conn.execute(f"UPDATE students SET {assignments} WHERE id = ?", (*fields.values(), student_id))
            if cur.rowcount == 0:
                return False, "Aluno não encontrado."
        return True, "Aluno atualizado com sucesso."
    except sqlite3.IntegrityError:
        return False, f"A matrícula '{fields['matricula']}' já pertence a outro aluno."
    except sqlite3.Error as e:
        return False, str(e)


def delete_student(student_id: int) -> Tuple[bool, str]:
    try:
        with connect() as conn:
            cur = conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
            if cur.rowcount == 0:
                return False, "Aluno não encontrado."
        return True, "Aluno excluído com sucesso."
    except sqlite3.Error as e:
        return False, str(e)


def bulk_delete_students(student_ids: List[int]) -> Tuple[bool, str]:
    if not student_ids:
        return False, "Nenhum aluno selecionado para exclusão."
    placeholders = ",".join("?" for _ in student_ids)
    try:
        with connect() as conn:
            cur = conn.execute(f"DELETE FROM students WHERE id IN ({placeholders})", student_ids)
            return True, f"{cur.rowcount} aluno(s) excluído(s) com sucesso."
    except sqlite3.Error as e:
        return False, str(e)


def verify_student_login(matricula: str, password: str) -> Tuple[bool, Any]:
    matricula, password = matricula.strip(), password.strip()
    if not matricula or not password:
        return False, "Matrícula e senha devem ser preenchidos."

    student = get_student_by_matricula(matricula)
    if not student or not verify_password(password, student["password_hash"], student["salt"]):
        return False, "Matrícula ou senha incorretos."

    return True, {k: student[k] for k in ("id", "matricula", "name", "turma")}


# ==========================================
# Importação de alunos por planilha (CSV)
# ==========================================
IMPORT_MAX_ROWS = 3000

_HEADER_ALIASES = {
    "matricula": "matricula", "matrícula": "matricula", "ra": "matricula", "codigo": "matricula",
    "código": "matricula", "id": "matricula",
    "nome": "name", "nome completo": "name", "aluno": "name", "name": "name", "nome do aluno": "name", "estudante": "name",
    "turma": "turma", "classe": "turma", "serie": "turma", "série": "turma", "sala": "turma",
    "senha": "password", "password": "password",
}
_DEFAULT_ORDER = ["matricula", "name", "turma", "password"]


def parse_students_csv(raw: bytes) -> Tuple[List[Tuple[int, Dict[str, str]]], Optional[str]]:
    """Lê um CSV (Excel salva em ';' e em Windows-1252) e devolve [(linha, campos)].

    Com cabeçalho reconhecido as colunas podem estar em qualquer ordem; sem cabeçalho a
    ordem esperada é: matrícula, nome, turma, senha.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return [], "Não foi possível ler o arquivo (codificação desconhecida)."

    lines = text.splitlines()
    sample = "\n".join(lines[:5])
    delimiter = max(";,\t", key=sample.count) if sample else ";"
    reader = csv.reader(lines, delimiter=delimiter)

    rows: List[Tuple[int, Dict[str, str]]] = []
    columns = _DEFAULT_ORDER
    for line_no, cells in enumerate(reader, start=1):
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if line_no == 1:
            mapped = [_HEADER_ALIASES.get(c.lower()) for c in cells]
            if "matricula" in mapped and "name" in mapped:
                columns = [m or "" for m in mapped]
                continue
        if len(rows) >= IMPORT_MAX_ROWS:
            return [], f"Arquivo com mais de {IMPORT_MAX_ROWS} alunos. Divida em partes."
        rows.append((line_no, {col: cells[i] for i, col in enumerate(columns) if col and i < len(cells)}))
    if not rows:
        return [], "Nenhum aluno encontrado no arquivo."
    return rows, None


def import_students(rows: List[Tuple[int, Dict[str, str]]], update_existing: bool = False) -> Dict[str, Any]:
    """Cadastra os alunos de uma vez. Senha em branco = a própria matrícula."""
    errors: List[str] = []
    inserts, updates = [], []
    seen = set()
    with connect() as conn:
        existing = {r[0] for r in conn.execute("SELECT matricula FROM students")}

    # Os hashes (lentos de propósito) são calculados antes de abrir a transação de escrita,
    # para não travar o banco (presença, logins) durante uma importação grande.
    for line_no, row in rows:
        matricula = row.get("matricula", "").strip()[:40]
        name = row.get("name", "").strip()[:150]
        turma = row.get("turma", "").strip()[:60]
        typed_password = row.get("password", "").strip()[:100]
        if not matricula or not name:
            errors.append(f"Linha {line_no}: matrícula e nome são obrigatórios.")
            continue
        if matricula in seen:
            errors.append(f"Linha {line_no}: matrícula {matricula} repetida no arquivo.")
            continue
        seen.add(matricula)
        if matricula in existing:
            if not update_existing:
                errors.append(f"Linha {line_no}: matrícula {matricula} já cadastrada (ignorada).")
                continue
            fields = {"name": name, "turma": turma}
            if typed_password:
                fields["password_hash"], fields["salt"] = hash_password(typed_password)
            updates.append((fields, matricula))
        else:
            pwd_hash, salt = hash_password(typed_password or matricula)
            inserts.append((matricula, name, turma, pwd_hash, salt))

    with connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO students (matricula, name, turma, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
            inserts,
        )
        for fields, matricula in updates:
            assignments = ", ".join(f"{col} = ?" for col in fields)
            conn.execute(f"UPDATE students SET {assignments} WHERE matricula = ?", (*fields.values(), matricula))
    return {"created": len(inserts), "updated": len(updates), "errors": errors}


# ==========================================
# Presença (histórico de login dos alunos por computador)
# ==========================================
def close_attendance(hostname: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE attendance SET logout_at = datetime('now', 'localtime') WHERE hostname = ? AND logout_at IS NULL",
            (hostname,),
        )


def touch_open_attendance() -> None:
    """Marca as sessões abertas como vistas agora (chamado periodicamente pelo servidor)."""
    with connect() as conn:
        conn.execute("UPDATE attendance SET last_seen = datetime('now', 'localtime') WHERE logout_at IS NULL")


def record_attendance(matricula: str, name: str, hostname: str, ip: str) -> str:
    """Abre uma sessão de presença (encerrando a anterior desse computador). Devolve a turma."""
    student = get_student_by_matricula(matricula)
    turma = student["turma"] if student else ""
    with connect() as conn:
        conn.execute(
            "UPDATE attendance SET logout_at = datetime('now', 'localtime') WHERE hostname = ? AND logout_at IS NULL",
            (hostname,),
        )
        conn.execute(
            "INSERT INTO attendance (matricula, student_name, turma, hostname, ip) VALUES (?, ?, ?, ?, ?)",
            (matricula, name, turma, hostname, ip),
        )
    return turma


# ==========================================
# Ocorrências (programas/sites bloqueados que os alunos tentaram usar)
# ==========================================
def record_event(hostname: str, student_name: str, kind: str, detail: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO events (hostname, student_name, kind, detail) VALUES (?, ?, ?, ?)",
                     (hostname, student_name, kind, detail))
        conn.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 5000")


def list_events(limit: int = 200) -> List[Dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, at, hostname, student_name, kind, detail FROM events ORDER BY id DESC LIMIT ?", (limit,))]


def list_attendance(start: Optional[str] = None, end: Optional[str] = None,
                    query: Optional[str] = None, limit: int = 2000) -> List[Dict[str, Any]]:
    where, params = [], []
    if start:
        where.append("login_at >= ?")
        params.append(start)
    if end:
        where.append("login_at < date(?, '+1 day')")
        params.append(end)
    if query and query.strip():
        q = f"%{query.strip()}%"
        where.append("(matricula LIKE ? OR student_name LIKE ? OR turma LIKE ? OR hostname LIKE ?)")
        params += [q, q, q, q]
    sql = "SELECT id, matricula, student_name, turma, hostname, ip, login_at, logout_at FROM attendance"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY login_at DESC LIMIT ?"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, (*params, limit)).fetchall()]


# ==========================================
# Equipe do TE (contas de acesso ao painel) e registro de ações
# ==========================================
ROLES = ("admin", "operador")
USER_PUBLIC = "id, email, name, role, must_change, active, created_at, last_login"
TEMP_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_temp_password(length: int = 10) -> str:
    return "".join(secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(length))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _public_user(row) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    user = {k: row[k] for k in row.keys() if k not in ("password_hash", "salt")}
    user["must_change"] = bool(user.get("must_change"))
    user["active"] = bool(user.get("active"))
    return user


def count_users() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def _active_admins(conn, excluding_id: Optional[int] = None) -> int:
    sql = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
    params: tuple = ()
    if excluding_id is not None:
        sql += " AND id != ?"
        params = (excluding_id,)
    return conn.execute(sql, params).fetchone()[0]


def get_user_auth(user_id: int) -> Optional[Dict[str, Any]]:
    """Usuário com o hash da senha (só para uso interno de autenticação)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (normalize_email(email),)).fetchone()
        return dict(row) if row else None


def list_users() -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(f"SELECT {USER_PUBLIC} FROM users ORDER BY name COLLATE NOCASE").fetchall()
        return [_public_user(r) for r in rows]


def create_user(email: str, name: str, role: str = "admin", password: Optional[str] = None,
                must_change: bool = True) -> Tuple[bool, Any]:
    """Cria a conta. Sem senha informada, gera uma provisória (devolvida em 'temp_password')."""
    email, name = normalize_email(email), " ".join((name or "").split())
    if role not in ROLES:
        return False, "Perfil inválido."
    if not name:
        return False, "Informe o nome."
    if email != "admin" and not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", email):
        return False, "Informe um e-mail válido."
    temp = password or generate_temp_password()
    pwd_hash, salt = hash_password(temp)
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash, salt, role, must_change) VALUES (?, ?, ?, ?, ?, ?)",
                (email, name, pwd_hash, salt, role, 1 if must_change else 0))
            user = _public_user(conn.execute(f"SELECT {USER_PUBLIC} FROM users WHERE id = ?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        return False, f"Já existe uma conta com o e-mail {email}."
    user["temp_password"] = None if password else temp
    return True, user


def update_user(user_id: int, name: str, role: str, active: bool) -> Tuple[bool, str]:
    name = " ".join((name or "").split())
    if not name or role not in ROLES:
        return False, "Nome ou perfil inválido."
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            return False, "Usuário não encontrado."
        if (role != "admin" or not active) and _active_admins(conn, excluding_id=user_id) == 0:
            return False, "É preciso manter pelo menos um administrador ativo."
        conn.execute("UPDATE users SET name = ?, role = ?, active = ? WHERE id = ?",
                     (name, role, 1 if active else 0, user_id))
    return True, "Usuário atualizado."


def set_user_password(user_id: int, password: str, must_change: bool) -> bool:
    pwd_hash, salt = hash_password(password)
    with connect() as conn:
        cur = conn.execute("UPDATE users SET password_hash = ?, salt = ?, must_change = ? WHERE id = ?",
                           (pwd_hash, salt, 1 if must_change else 0, user_id))
        return cur.rowcount > 0


def reset_user_password(user_id: int) -> Optional[str]:
    temp = generate_temp_password()
    return temp if set_user_password(user_id, temp, True) else None


def delete_user(user_id: int) -> Tuple[bool, str]:
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            return False, "Usuário não encontrado."
        if _active_admins(conn, excluding_id=user_id) == 0:
            return False, "É preciso manter pelo menos um administrador ativo."
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True, "Usuário removido."


def touch_login(user_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET last_login = datetime('now', 'localtime') WHERE id = ?", (user_id,))


def record_audit(user_email: str, user_name: str, action: str, detail: str = "") -> None:
    with connect() as conn:
        conn.execute("INSERT INTO audit (user_email, user_name, action, detail) VALUES (?, ?, ?, ?)",
                     (user_email, user_name, action, detail[:300]))
        conn.execute("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - 20000")


def list_audit(limit: int = 300) -> List[Dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, at, user_email, user_name, action, detail FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
