import csv
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from config import DB_PATH

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
