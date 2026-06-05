"""
NutriNext Pro — Database layer
Supporta PostgreSQL (produzione) e SQLite (sviluppo locale).
Configura DATABASE_URL come variabile d'ambiente per usare PostgreSQL.
"""

import os
import sqlite3
import hashlib
import secrets
import string
from contextlib import contextmanager
from datetime import datetime, timedelta

# ── Carica .env se presente ───────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)
# Path assoluto → il DB è sempre nella cartella dell'app, indipendentemente da dove si lancia
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nutrigen.db")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.pool
    _pg_pool = None

def _get_pg_pool():
    global _pg_pool
    if not USE_POSTGRES:
        return None
    if _pg_pool is None:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, DATABASE_URL)
    return _pg_pool


# ==============================================================================
# CONNECTION CONTEXT MANAGER
# ==============================================================================

class _Cursor:
    """Wrapper che normalizza sqlite3 e psycopg2 (placeholder, lastrowid)."""
    def __init__(self, cur, conn, use_pg):
        self._cur  = cur
        self._conn = conn
        self._pg   = use_pg

    def execute(self, sql, params=()):
        if not self._pg:
            sql = sql.replace("%s", "?")
        self._cur.execute(sql, params)
        return self

    def executemany(self, sql, seq):
        if not self._pg:
            sql = sql.replace("%s", "?")
        self._cur.executemany(sql, seq)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        if self._pg:
            row = self._cur.fetchone()
            return row[0] if row else None
        return self._cur.lastrowid

    def __iter__(self):
        return iter(self._cur)


@contextmanager
def _conn():
    if USE_POSTGRES:
        con = _get_pg_pool().getconn()
        con.autocommit = False
        try:
            cur = con.cursor()
            yield _Cursor(cur, con, True)
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            cur.close()
            _get_pg_pool().putconn(con)
    else:
        con = sqlite3.connect(DB_FILE, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            cur = con.cursor()
            yield _Cursor(cur, con, False)
            con.commit()
        finally:
            cur.close()
            con.close()


def _row_to_dict(row):
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):           # sqlite3.Row
        return dict(row)
    if USE_POSTGRES:
        # psycopg2 restituisce tuple — usiamo description del cursor
        return row
    return dict(row)


# ==============================================================================
# INIT / MIGRATION
# ==============================================================================

def _pg_init(cur):
    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            id               SERIAL PRIMARY KEY,
            username         TEXT UNIQUE NOT NULL,
            password_hash    TEXT NOT NULL,
            nome             TEXT NOT NULL,
            cognome          TEXT DEFAULT '',
            role             TEXT NOT NULL CHECK(role IN ('nutritionist','patient','superadmin')),
            studio_code      TEXT UNIQUE,
            sesso_nut        TEXT DEFAULT 'M',
            specializzazione TEXT DEFAULT 'Nutrizionista',
            email_studio     TEXT DEFAULT '',
            telefono         TEXT DEFAULT '',
            logo_path        TEXT DEFAULT '',
            logo_data        TEXT DEFAULT '',
            last_login       TIMESTAMPTZ,
            is_active        INTEGER DEFAULT 1,
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS invite_tokens (
            id               SERIAL PRIMARY KEY,
            nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
            token            TEXT UNIQUE NOT NULL,
            expires_at       TIMESTAMPTZ NOT NULL,
            used             INTEGER DEFAULT 0,
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS patient_requests (
            id               SERIAL PRIMARY KEY,
            nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
            nome             TEXT NOT NULL,
            cognome          TEXT DEFAULT '',
            email            TEXT DEFAULT '',
            sesso            TEXT,
            data_nascita     TEXT,
            username         TEXT NOT NULL,
            password_hash    TEXT NOT NULL,
            stato            TEXT DEFAULT 'In attesa',
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS patients (
            id               SERIAL PRIMARY KEY,
            nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
            username         TEXT UNIQUE,
            password_hash    TEXT,
            nome             TEXT NOT NULL,
            cognome          TEXT DEFAULT '',
            email            TEXT DEFAULT '',
            sesso            TEXT CHECK(sesso IN ('M','F')),
            data_nascita     TEXT,
            telefono         TEXT DEFAULT '',
            note_anamnesi    TEXT DEFAULT '',
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS appointments (
            id               SERIAL PRIMARY KEY,
            nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
            patient_id       INTEGER REFERENCES patients(id),
            patient_name     TEXT,
            data_ora         TEXT NOT NULL,
            durata_min       INTEGER DEFAULT 60,
            tipo             TEXT DEFAULT 'Prima Visita',
            note             TEXT DEFAULT '',
            stato            TEXT DEFAULT 'Programmato',
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS visits (
            id        SERIAL PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            data      TEXT NOT NULL,
            peso REAL, altezza REAL, eta INTEGER, sesso TEXT,
            R REAL, Xc REAL,
            PhA REAL, TBW REAL, ECW REAL, ICW REAL,
            FFM REAL, FM REAL, FM_perc REAL,
            BCM REAL, SMM REAL, ASMM REAL, BMR INTEGER,
            pliche_tricipitale REAL DEFAULT 0,
            pliche_bicipitale REAL DEFAULT 0,
            pliche_sottoscapolare REAL DEFAULT 0,
            pliche_soprailiaca REAL DEFAULT 0,
            pliche_addominale REAL DEFAULT 0,
            pliche_coscia REAL DEFAULT 0,
            pliche_ascellare REAL DEFAULT 0,
            note TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS diet_plans (
            id              SERIAL PRIMARY KEY,
            patient_id      INTEGER NOT NULL REFERENCES patients(id),
            visit_id        INTEGER REFERENCES visits(id),
            nome            TEXT DEFAULT 'Piano attivo',
            note            TEXT DEFAULT '',
            freq_proteiche  TEXT DEFAULT '',
            is_active       INTEGER DEFAULT 1,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS diet_items (
            id       SERIAL PRIMARY KEY,
            plan_id  INTEGER NOT NULL REFERENCES diet_plans(id) ON DELETE CASCADE,
            giorno TEXT, pasto TEXT, alimento TEXT, quantita REAL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS messages (
            id         SERIAL PRIMARY KEY,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            ruolo      TEXT NOT NULL,
            testo      TEXT NOT NULL,
            timestamp  TIMESTAMPTZ DEFAULT NOW(),
            letto      INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS templates (
            id               SERIAL PRIMARY KEY,
            nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
            nome             TEXT NOT NULL,
            note             TEXT DEFAULT '',
            items_json       TEXT DEFAULT '[]',
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS bug_reports (
            id               SERIAL PRIMARY KEY,
            nutritionist_id  INTEGER REFERENCES users(id),
            titolo           TEXT NOT NULL,
            descrizione      TEXT NOT NULL,
            categoria        TEXT DEFAULT 'Generale',
            priorita         TEXT DEFAULT 'Media',
            stato            TEXT DEFAULT 'Aperto',
            admin_note       TEXT DEFAULT '',
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            resolved_at      TIMESTAMPTZ
        )""",
        """CREATE TABLE IF NOT EXISTS nutritionist_requests (
            id               SERIAL PRIMARY KEY,
            nome             TEXT NOT NULL,
            cognome          TEXT DEFAULT '',
            sesso_nut        TEXT DEFAULT 'M',
            specializzazione TEXT DEFAULT 'Nutrizionista',
            email_studio     TEXT DEFAULT '',
            telefono         TEXT DEFAULT '',
            username         TEXT NOT NULL,
            password_hash    TEXT NOT NULL,
            stato            TEXT DEFAULT 'In attesa',
            admin_note       TEXT DEFAULT '',
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )""",
    ]
    for stmt in stmts:
        cur.execute(stmt)


def _sqlite_init(cur):
    cur._cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        username         TEXT UNIQUE NOT NULL,
        password_hash    TEXT NOT NULL,
        nome             TEXT NOT NULL,
        cognome          TEXT DEFAULT '',
        role             TEXT NOT NULL CHECK(role IN ('nutritionist','patient','superadmin')),
        studio_code      TEXT UNIQUE,
        sesso_nut        TEXT DEFAULT 'M',
        specializzazione TEXT DEFAULT 'Nutrizionista',
        email_studio     TEXT DEFAULT '',
        telefono         TEXT DEFAULT '',
        logo_path        TEXT DEFAULT '',
        logo_data        TEXT DEFAULT '',
        last_login       TEXT,
        is_active        INTEGER DEFAULT 1,
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS invite_tokens (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
        token            TEXT UNIQUE NOT NULL,
        expires_at       TEXT NOT NULL,
        used             INTEGER DEFAULT 0,
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS patient_requests (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
        nome             TEXT NOT NULL,
        cognome          TEXT DEFAULT '',
        email            TEXT DEFAULT '',
        sesso            TEXT,
        data_nascita     TEXT,
        username         TEXT NOT NULL,
        password_hash    TEXT NOT NULL,
        stato            TEXT DEFAULT 'In attesa',
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS patients (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
        username         TEXT UNIQUE,
        password_hash    TEXT,
        nome             TEXT NOT NULL,
        cognome          TEXT DEFAULT '',
        email            TEXT DEFAULT '',
        sesso            TEXT CHECK(sesso IN ('M','F')),
        data_nascita     TEXT,
        telefono         TEXT DEFAULT '',
        note_anamnesi    TEXT DEFAULT '',
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS appointments (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
        patient_id       INTEGER REFERENCES patients(id),
        patient_name     TEXT,
        data_ora         TEXT NOT NULL,
        durata_min       INTEGER DEFAULT 60,
        tipo             TEXT DEFAULT 'Prima Visita',
        note             TEXT DEFAULT '',
        stato            TEXT DEFAULT 'Programmato',
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS visits (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        data TEXT NOT NULL,
        peso REAL, altezza REAL, eta INTEGER, sesso TEXT,
        R REAL, Xc REAL,
        PhA REAL, TBW REAL, ECW REAL, ICW REAL,
        FFM REAL, FM REAL, FM_perc REAL,
        BCM REAL, SMM REAL, ASMM REAL, BMR INTEGER,
        pliche_tricipitale REAL DEFAULT 0,
        pliche_bicipitale REAL DEFAULT 0,
        pliche_sottoscapolare REAL DEFAULT 0,
        pliche_soprailiaca REAL DEFAULT 0,
        pliche_addominale REAL DEFAULT 0,
        pliche_coscia REAL DEFAULT 0,
        pliche_ascellare REAL DEFAULT 0,
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS diet_plans (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id      INTEGER NOT NULL REFERENCES patients(id),
        visit_id        INTEGER REFERENCES visits(id),
        nome            TEXT DEFAULT 'Piano attivo',
        note            TEXT DEFAULT '',
        freq_proteiche  TEXT DEFAULT '',
        is_active       INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS diet_items (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id  INTEGER NOT NULL REFERENCES diet_plans(id) ON DELETE CASCADE,
        giorno TEXT, pasto TEXT, alimento TEXT, quantita REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS messages (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        ruolo      TEXT NOT NULL,
        testo      TEXT NOT NULL,
        timestamp  TEXT DEFAULT (datetime('now')),
        letto      INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS templates (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nutritionist_id  INTEGER NOT NULL REFERENCES users(id),
        nome             TEXT NOT NULL,
        note             TEXT DEFAULT '',
        items_json       TEXT DEFAULT '[]',
        created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS bug_reports (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nutritionist_id  INTEGER REFERENCES users(id),
        titolo           TEXT NOT NULL,
        descrizione      TEXT NOT NULL,
        categoria        TEXT DEFAULT 'Generale',
        priorita         TEXT DEFAULT 'Media',
        stato            TEXT DEFAULT 'Aperto',
        admin_note       TEXT DEFAULT '',
        created_at       TEXT DEFAULT (datetime('now')),
        resolved_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS nutritionist_requests (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nome             TEXT NOT NULL,
        cognome          TEXT DEFAULT '',
        sesso_nut        TEXT DEFAULT 'M',
        specializzazione TEXT DEFAULT 'Nutrizionista',
        email_studio     TEXT DEFAULT '',
        telefono         TEXT DEFAULT '',
        username         TEXT NOT NULL,
        password_hash    TEXT NOT NULL,
        stato            TEXT DEFAULT 'In attesa',
        admin_note       TEXT DEFAULT '',
        created_at       TEXT DEFAULT (datetime('now'))
    );
    """)
    # Migration colonne mancanti
    _migrations = [
        ("users", "studio_code",      "TEXT"),
        ("users", "sesso_nut",        "TEXT DEFAULT 'M'"),
        ("users", "specializzazione", "TEXT DEFAULT 'Nutrizionista'"),
        ("users", "email_studio",     "TEXT DEFAULT ''"),
        ("users", "telefono",         "TEXT DEFAULT ''"),
        ("users", "logo_path",        "TEXT DEFAULT ''"),
        ("users", "logo_data",        "TEXT DEFAULT ''"),
        ("users", "last_login",       "TEXT"),
        ("users",       "is_active",        "INTEGER DEFAULT 1"),
        ("diet_plans",  "freq_proteiche",   "TEXT DEFAULT ''"),
    ]
    for table, col, typedef in _migrations:
        try:
            cur._cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        except Exception:
            pass


def _pg_migrate(cur):
    """Applica colonne mancanti su PostgreSQL (idempotente)."""
    migrations = [
        ("users",       "is_active",       "INTEGER DEFAULT 1"),
        ("diet_plans",  "freq_proteiche",  "TEXT DEFAULT ''"),
        ("nutritionist_requests", "id",    None),  # solo check esistenza tabella
    ]
    for table, col, typedef in migrations:
        if typedef is None:
            continue
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # colonna già esistente


def init_db():
    with _conn() as cur:
        if USE_POSTGRES:
            _pg_init(cur)
            _pg_migrate(cur)
        else:
            _sqlite_init(cur)


def _normalize(d: dict) -> dict:
    """Convert datetime/date values to ISO strings for uniform handling."""
    from datetime import datetime as _dt, date as _date
    return {k: (v.isoformat() if isinstance(v, (_dt, _date)) else v) for k, v in d.items()}


def _fetchall(cur) -> list:
    rows = cur.fetchall()
    if not rows:
        return []
    if USE_POSTGRES:
        cols = [d[0] for d in cur._cur.description]
        return [_normalize(dict(zip(cols, r))) for r in rows]
    return [_normalize(dict(r)) for r in rows]


def _fetchone(cur) -> dict:
    row = cur.fetchone()
    if not row:
        return {}
    if USE_POSTGRES:
        cols = [d[0] for d in cur._cur.description]
        return _normalize(dict(zip(cols, row)))
    return _normalize(dict(row))


# ==============================================================================
# AUTH
# ==============================================================================

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _gen_studio_code() -> str:
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(chars) for _ in range(6))
        with _conn() as cur:
            cur.execute("SELECT 1 FROM users WHERE studio_code=%s", (code,))
            if not cur.fetchone():
                return code

def setup_nutritionist(username, password, nome, cognome="",
                       sesso_nut="M", specializzazione="Nutrizionista",
                       email_studio="", telefono=""):
    code = _gen_studio_code()
    ret  = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        cur.execute(
            f"""INSERT INTO users
               (username,password_hash,nome,cognome,role,studio_code,
                sesso_nut,specializzazione,email_studio,telefono)
               VALUES (%s,%s,%s,%s,'nutritionist',%s,%s,%s,%s,%s){ret}""",
            (username, _hash(password), nome, cognome, code,
             sesso_nut, specializzazione, email_studio, telefono)
        )

def update_nutritionist_profile(user_id, nome, cognome, sesso_nut,
                                 specializzazione, email_studio, telefono,
                                 logo_path=None):
    with _conn() as cur:
        if logo_path is not None:
            cur.execute("""UPDATE users SET nome=%s,cognome=%s,sesso_nut=%s,specializzazione=%s,
                email_studio=%s,telefono=%s,logo_path=%s WHERE id=%s""",
                (nome,cognome,sesso_nut,specializzazione,email_studio,telefono,logo_path,user_id))
        else:
            cur.execute("""UPDATE users SET nome=%s,cognome=%s,sesso_nut=%s,specializzazione=%s,
                email_studio=%s,telefono=%s WHERE id=%s""",
                (nome,cognome,sesso_nut,specializzazione,email_studio,telefono,user_id))

def has_nutritionist() -> bool:
    with _conn() as cur:
        cur.execute("SELECT 1 FROM users WHERE role='nutritionist' LIMIT 1")
        return bool(cur.fetchone())

def has_superadmin() -> bool:
    with _conn() as cur:
        cur.execute("SELECT 1 FROM users WHERE role='superadmin' LIMIT 1")
        return bool(cur.fetchone())

def setup_superadmin(username, password, nome, cognome=""):
    ret = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        cur.execute(
            f"INSERT INTO users (username,password_hash,nome,cognome,role) VALUES (%s,%s,%s,%s,'superadmin'){ret}",
            (username, _hash(password), nome, cognome)
        )

def login(username: str, password: str):
    with _conn() as cur:
        cur.execute("SELECT * FROM users WHERE username=%s AND password_hash=%s",
            (username, _hash(password)))
        row = _fetchone(cur)
        if row:
            if row.get("is_active", 1) == 0:
                return {"_suspended": True}
            # Aggiorna last_login
            with _conn() as cur2:
                cur2.execute("UPDATE users SET last_login=%s WHERE id=%s",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"), row["id"]))
            return row
    with _conn() as cur:
        cur.execute(
            """SELECT p.*, u.username as nut_username FROM patients p
               JOIN users u ON u.id=p.nutritionist_id
               WHERE p.username=%s AND p.password_hash=%s""",
            (username, _hash(password))
        )
        row = _fetchone(cur)
        return {"_patient": True, **row} if row else None

def get_nutritionist(nut_id: int) -> dict:
    with _conn() as cur:
        cur.execute("SELECT * FROM users WHERE id=%s", (nut_id,))
        return _fetchone(cur)

def save_logo_data(user_id: int, b64: str):
    with _conn() as cur:
        cur.execute("UPDATE users SET logo_data=%s WHERE id=%s", (b64, user_id))

def get_logo_data(user_id: int) -> str:
    with _conn() as cur:
        cur.execute("SELECT logo_data FROM users WHERE id=%s", (user_id,))
        row = _fetchone(cur)
        return row.get("logo_data", "") if row else ""

def get_nutritionist_by_code(code: str) -> dict:
    with _conn() as cur:
        cur.execute("SELECT * FROM users WHERE studio_code=%s AND role='nutritionist'",
            (code.upper().strip(),))
        return _fetchone(cur)


# ==============================================================================
# PATIENTS
# ==============================================================================

def get_patients(nutritionist_id: int) -> list:
    with _conn() as cur:
        cur.execute("SELECT * FROM patients WHERE nutritionist_id=%s ORDER BY cognome,nome",
            (nutritionist_id,))
        return _fetchall(cur)

def get_patient(patient_id: int) -> dict:
    with _conn() as cur:
        cur.execute("SELECT * FROM patients WHERE id=%s", (patient_id,))
        return _fetchone(cur)

def save_patient(nutritionist_id, nome, cognome, email, sesso, data_nascita,
                 telefono, note_anamnesi, username="", password="", patient_id=None):
    ph  = _hash(password) if password else None
    ret = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        if patient_id:
            if password:
                cur.execute("""UPDATE patients SET nome=%s,cognome=%s,email=%s,sesso=%s,
                    data_nascita=%s,telefono=%s,note_anamnesi=%s,username=%s,password_hash=%s
                    WHERE id=%s""",
                    (nome,cognome,email,sesso,data_nascita,telefono,note_anamnesi,username,ph,patient_id))
            else:
                cur.execute("""UPDATE patients SET nome=%s,cognome=%s,email=%s,sesso=%s,
                    data_nascita=%s,telefono=%s,note_anamnesi=%s,username=%s WHERE id=%s""",
                    (nome,cognome,email,sesso,data_nascita,telefono,note_anamnesi,username,patient_id))
        else:
            cur.execute(
                f"""INSERT INTO patients
                    (nutritionist_id,nome,cognome,email,sesso,data_nascita,
                     telefono,note_anamnesi,username,password_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s){ret}""",
                (nutritionist_id,nome,cognome,email,sesso,data_nascita,
                 telefono,note_anamnesi,username,ph)
            )
            return cur.lastrowid


# ==============================================================================
# APPOINTMENTS
# ==============================================================================

def get_appointments(nutritionist_id: int, from_date=None, to_date=None) -> list:
    with _conn() as cur:
        if from_date and to_date:
            cur.execute(
                "SELECT * FROM appointments WHERE nutritionist_id=%s AND data_ora BETWEEN %s AND %s ORDER BY data_ora",
                (nutritionist_id, from_date, to_date))
        else:
            cur.execute("SELECT * FROM appointments WHERE nutritionist_id=%s ORDER BY data_ora",
                (nutritionist_id,))
        return _fetchall(cur)

def save_appointment(nutritionist_id, patient_id, patient_name, data_ora,
                     durata_min, tipo, note, stato, appt_id=None):
    ret = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        if appt_id:
            cur.execute("""UPDATE appointments SET patient_id=%s,patient_name=%s,data_ora=%s,
                durata_min=%s,tipo=%s,note=%s,stato=%s WHERE id=%s""",
                (patient_id,patient_name,data_ora,durata_min,tipo,note,stato,appt_id))
        else:
            cur.execute(
                f"""INSERT INTO appointments
                    (nutritionist_id,patient_id,patient_name,data_ora,durata_min,tipo,note,stato)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s){ret}""",
                (nutritionist_id,patient_id,patient_name,data_ora,durata_min,tipo,note,stato))

def delete_appointment(appt_id: int):
    with _conn() as cur:
        cur.execute("DELETE FROM appointments WHERE id=%s", (appt_id,))


# ==============================================================================
# VISITS
# ==============================================================================

def save_visit(patient_id, data, peso, altezza, eta, sesso, R, Xc,
               bia: dict, bmr, pliche: dict, note=""):
    ret = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        cur.execute(
            f"""INSERT INTO visits
                (patient_id,data,peso,altezza,eta,sesso,R,Xc,
                 PhA,TBW,ECW,ICW,FFM,FM,FM_perc,BCM,SMM,ASMM,BMR,
                 pliche_tricipitale,pliche_bicipitale,pliche_sottoscapolare,
                 pliche_soprailiaca,pliche_addominale,pliche_coscia,pliche_ascellare,note)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s){ret}""",
            (patient_id,data,peso,altezza,eta,sesso,R,Xc,
             bia["PhA"],bia["TBW"],bia["ECW"],bia["ICW"],
             bia["FFM"],bia["FM"],bia["FM%"],bia["BCM"],bia["SMM"],bia["ASMM"],bmr,
             pliche.get("tricipitale",0),pliche.get("bicipitale",0),
             pliche.get("sottoscapolare",0),pliche.get("soprailiaca",0),
             pliche.get("addominale",0),pliche.get("coscia",0),pliche.get("ascellare",0),note))
        return cur.lastrowid

def get_visits(patient_id: int) -> list:
    with _conn() as cur:
        cur.execute("SELECT * FROM visits WHERE patient_id=%s ORDER BY data DESC", (patient_id,))
        return _fetchall(cur)

def get_latest_visit(patient_id: int) -> dict:
    visits = get_visits(patient_id)
    return visits[0] if visits else {}


# ==============================================================================
# DIET PLANS
# ==============================================================================

def get_active_plan(patient_id: int) -> dict:
    with _conn() as cur:
        cur.execute("""SELECT * FROM diet_plans WHERE patient_id=%s AND is_active=1
            ORDER BY created_at DESC LIMIT 1""", (patient_id,))
        return _fetchone(cur)

def get_plan_items(plan_id: int) -> list:
    with _conn() as cur:
        cur.execute("SELECT * FROM diet_items WHERE plan_id=%s ORDER BY giorno,pasto", (plan_id,))
        return _fetchall(cur)

def save_plan(patient_id, items: list, note="", nome="Piano attivo",
              visit_id=None, freq_proteiche="") -> int:
    ret = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        cur.execute("UPDATE diet_plans SET is_active=0 WHERE patient_id=%s", (patient_id,))
        cur.execute(
            f"INSERT INTO diet_plans (patient_id,visit_id,nome,note,freq_proteiche,is_active) VALUES (%s,%s,%s,%s,%s,1){ret}",
            (patient_id, visit_id, nome, note, freq_proteiche))
        plan_id = cur.lastrowid
        for item in items:
            cur.execute(
                "INSERT INTO diet_items (plan_id,giorno,pasto,alimento,quantita) VALUES (%s,%s,%s,%s,%s)",
                (plan_id, item.get("Giorno"), item.get("Pasto"),
                 item.get("Alimento"), item.get("Quantità", 0)))
        return plan_id


# ==============================================================================
# MESSAGES
# ==============================================================================

def get_messages(patient_id: int) -> list:
    with _conn() as cur:
        cur.execute("SELECT * FROM messages WHERE patient_id=%s ORDER BY timestamp", (patient_id,))
        return _fetchall(cur)

def send_message(patient_id: int, ruolo: str, testo: str):
    with _conn() as cur:
        cur.execute("INSERT INTO messages (patient_id,ruolo,testo) VALUES (%s,%s,%s)",
            (patient_id, ruolo, testo))
    mark_read(patient_id, "Nutrizionista" if ruolo == "Paziente" else "Paziente")

def mark_read(patient_id: int, ruolo_destinatario: str):
    with _conn() as cur:
        cur.execute("UPDATE messages SET letto=1 WHERE patient_id=%s AND ruolo!=%s AND letto=0",
            (patient_id, ruolo_destinatario))

def unread_count(patient_id: int, ruolo_destinatario: str) -> int:
    with _conn() as cur:
        cur.execute("SELECT COUNT(*) FROM messages WHERE patient_id=%s AND ruolo!=%s AND letto=0",
            (patient_id, ruolo_destinatario))
        row = cur.fetchone()
        return row[0] if row else 0


# ==============================================================================
# TEMPLATES
# ==============================================================================

def get_templates(nutritionist_id: int) -> list:
    with _conn() as cur:
        cur.execute("SELECT * FROM templates WHERE nutritionist_id=%s ORDER BY nome", (nutritionist_id,))
        return _fetchall(cur)

def save_template(nutritionist_id, nome, note, items_json):
    with _conn() as cur:
        cur.execute("SELECT 1 FROM templates WHERE nutritionist_id=%s AND nome=%s", (nutritionist_id, nome))
        if cur.fetchone():
            cur.execute("UPDATE templates SET note=%s,items_json=%s WHERE nutritionist_id=%s AND nome=%s",
                (note, items_json, nutritionist_id, nome))
        else:
            cur.execute("INSERT INTO templates (nutritionist_id,nome,note,items_json) VALUES (%s,%s,%s,%s)",
                (nutritionist_id, nome, note, items_json))

def delete_template(template_id: int):
    with _conn() as cur:
        cur.execute("DELETE FROM templates WHERE id=%s", (template_id,))


# ==============================================================================
# INVITE TOKENS
# ==============================================================================

def create_invite_token(nutritionist_id: int, days_valid: int = 7) -> str:
    token   = secrets.token_urlsafe(24)
    expires = (datetime.now() + timedelta(days=days_valid)).strftime("%Y-%m-%d %H:%M")
    with _conn() as cur:
        cur.execute("INSERT INTO invite_tokens (nutritionist_id,token,expires_at) VALUES (%s,%s,%s)",
            (nutritionist_id, token, expires))
    return token

def get_token_info(token: str) -> dict:
    with _conn() as cur:
        ts = "NOW()" if USE_POSTGRES else "datetime('now')"
        cur.execute(
            f"""SELECT t.*, u.nome, u.cognome, u.studio_code FROM invite_tokens t
                JOIN users u ON u.id=t.nutritionist_id
                WHERE t.token=%s AND t.used=0 AND t.expires_at > {ts}""", (token,))
        return _fetchone(cur)

def use_token(token: str):
    with _conn() as cur:
        cur.execute("UPDATE invite_tokens SET used=1 WHERE token=%s", (token,))


# ==============================================================================
# PATIENT REQUESTS
# ==============================================================================

def submit_patient_request(nutritionist_id, nome, cognome, email, sesso,
                            data_nascita, username, password):
    with _conn() as cur:
        cur.execute("SELECT 1 FROM patients WHERE username=%s", (username,))
        if cur.fetchone():
            return False, "Username già in uso."
        cur.execute("SELECT 1 FROM patient_requests WHERE username=%s", (username,))
        if cur.fetchone():
            return False, "Richiesta già inviata con questo username."
        cur.execute("""INSERT INTO patient_requests
            (nutritionist_id,nome,cognome,email,sesso,data_nascita,username,password_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (nutritionist_id,nome,cognome,email,sesso,data_nascita,username,_hash(password)))
        return True, "Richiesta inviata. Il nutrizionista riceverà una notifica."

def get_pending_requests(nutritionist_id: int) -> list:
    with _conn() as cur:
        cur.execute("""SELECT * FROM patient_requests WHERE nutritionist_id=%s AND stato='In attesa'
            ORDER BY created_at DESC""", (nutritionist_id,))
        return _fetchall(cur)

def approve_request(request_id: int):
    with _conn() as cur:
        cur.execute("SELECT * FROM patient_requests WHERE id=%s", (request_id,))
        req = _fetchone(cur)
        if not req:
            return
    with _conn() as cur:
        cur.execute("""INSERT INTO patients
            (nutritionist_id,nome,cognome,email,sesso,data_nascita,username,password_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (req["nutritionist_id"],req["nome"],req["cognome"],req["email"],
             req["sesso"],req["data_nascita"],req["username"],req["password_hash"]))
        cur.execute("UPDATE patient_requests SET stato='Approvato' WHERE id=%s", (request_id,))

def reject_request(request_id: int):
    with _conn() as cur:
        cur.execute("UPDATE patient_requests SET stato='Rifiutato' WHERE id=%s", (request_id,))


# ==============================================================================
# BUG REPORTS
# ==============================================================================

def submit_bug(nutritionist_id, titolo, descrizione, categoria="Generale", priorita="Media"):
    with _conn() as cur:
        cur.execute("""INSERT INTO bug_reports
            (nutritionist_id,titolo,descrizione,categoria,priorita)
            VALUES (%s,%s,%s,%s,%s)""",
            (nutritionist_id, titolo, descrizione, categoria, priorita))

def get_all_bugs(stato=None) -> list:
    with _conn() as cur:
        if stato:
            cur.execute("""SELECT b.*, u.nome as nut_nome, u.cognome as nut_cognome,
                u.email_studio FROM bug_reports b
                LEFT JOIN users u ON u.id=b.nutritionist_id
                WHERE b.stato=%s ORDER BY b.created_at DESC""", (stato,))
        else:
            cur.execute("""SELECT b.*, u.nome as nut_nome, u.cognome as nut_cognome,
                u.email_studio FROM bug_reports b
                LEFT JOIN users u ON u.id=b.nutritionist_id
                ORDER BY b.created_at DESC""")
        return _fetchall(cur)

def update_bug(bug_id, stato, admin_note=""):
    resolved = datetime.now().strftime("%Y-%m-%d %H:%M") if stato == "Risolto" else None
    with _conn() as cur:
        cur.execute("UPDATE bug_reports SET stato=%s,admin_note=%s,resolved_at=%s WHERE id=%s",
            (stato, admin_note, resolved, bug_id))


# ==============================================================================
# ADMIN — ricerca pazienti
# ==============================================================================

def search_patients(query: str) -> list:
    """Cerca pazienti per nome, cognome o username su tutta la piattaforma."""
    q = f"%{query.strip()}%"
    if USE_POSTGRES:
        sql = """
            SELECT p.id, p.nome, p.cognome, p.email, p.sesso, p.data_nascita,
                   p.username, p.telefono, p.created_at,
                   u.nome as nut_nome, u.cognome as nut_cognome,
                   u.studio_code, u.email_studio as nut_email
            FROM patients p
            JOIN users u ON u.id = p.nutritionist_id
            WHERE p.nome ILIKE %s OR p.cognome ILIKE %s OR p.username ILIKE %s
            ORDER BY p.cognome, p.nome
        """
    else:
        sql = """
            SELECT p.id, p.nome, p.cognome, p.email, p.sesso, p.data_nascita,
                   p.username, p.telefono, p.created_at,
                   u.nome as nut_nome, u.cognome as nut_cognome,
                   u.studio_code, u.email_studio as nut_email
            FROM patients p
            JOIN users u ON u.id = p.nutritionist_id
            WHERE p.nome LIKE %s OR p.cognome LIKE %s OR p.username LIKE %s
            ORDER BY p.cognome, p.nome
        """
    with _conn() as cur:
        cur.execute(sql, (q, q, q))
        return _fetchall(cur)


# ==============================================================================
# ADMIN — statistiche
# ==============================================================================

def get_all_nutritionists() -> list:
    with _conn() as cur:
        cur.execute("""SELECT u.*,
            (SELECT COUNT(*) FROM patients p WHERE p.nutritionist_id=u.id) as n_pazienti,
            (SELECT COUNT(*) FROM diet_plans d JOIN patients p ON p.id=d.patient_id
                WHERE p.nutritionist_id=u.id) as n_piani,
            (SELECT COUNT(*) FROM bug_reports b WHERE b.nutritionist_id=u.id
                AND b.stato='Aperto') as n_bug_aperti
            FROM users u WHERE u.role='nutritionist'
            ORDER BY u.created_at DESC""")
        return _fetchall(cur)

def get_platform_stats() -> dict:
    with _conn() as cur:
        stats = {}
        for key, sql in [
            ("tot_nutrizionisti", "SELECT COUNT(*) FROM users WHERE role='nutritionist'"),
            ("tot_pazienti",      "SELECT COUNT(*) FROM patients"),
            ("tot_piani",         "SELECT COUNT(*) FROM diet_plans"),
            ("tot_visite",        "SELECT COUNT(*) FROM visits"),
            ("tot_messaggi",      "SELECT COUNT(*) FROM messages"),
            ("bug_aperti",        "SELECT COUNT(*) FROM bug_reports WHERE stato='Aperto'"),
        ]:
            cur.execute(sql)
            row = cur.fetchone()
            stats[key] = row[0] if row else 0
        return stats

# ==============================================================================
# RECUPERO CREDENZIALI
# ==============================================================================

def find_user_by_email(email: str):
    """Cerca un nutrizionista per email studio."""
    with _conn() as cur:
        cur.execute("SELECT * FROM users WHERE email_studio=%s AND role='nutritionist'", (email,))
        return _fetchone(cur)

def find_patient_by_email(email: str):
    """Cerca un paziente per email."""
    with _conn() as cur:
        cur.execute("SELECT * FROM patients WHERE email=%s", (email,))
        return _fetchone(cur)

def reset_password(user_type: str, user_id: int, new_password: str):
    """Aggiorna la password — user_type: 'nutritionist' o 'patient'."""
    ph = _hash(new_password)
    with _conn() as cur:
        if user_type == "nutritionist":
            cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (ph, user_id))
        else:
            cur.execute("UPDATE patients SET password_hash=%s WHERE id=%s", (ph, user_id))


# ==============================================================================
# RICHIESTE REGISTRAZIONE NUTRIZIONISTA
# ==============================================================================

def submit_nutritionist_request(nome, cognome, sesso_nut, specializzazione,
                                 email_studio, telefono, username, password) -> tuple:
    with _conn() as cur:
        cur.execute("SELECT 1 FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            return False, "Username già in uso da un altro account."
        cur.execute("SELECT 1 FROM nutritionist_requests WHERE username=%s AND stato='In attesa'", (username,))
        if cur.fetchone():
            return False, "Hai già una richiesta in attesa con questo username."
        cur.execute("""INSERT INTO nutritionist_requests
            (nome,cognome,sesso_nut,specializzazione,email_studio,telefono,username,password_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (nome, cognome, sesso_nut, specializzazione, email_studio,
             telefono, username, _hash(password)))
        return True, "Richiesta inviata. Riceverai conferma non appena l'amministratore la approverà."

def get_pending_nutritionist_requests() -> list:
    with _conn() as cur:
        cur.execute("""SELECT * FROM nutritionist_requests WHERE stato='In attesa'
            ORDER BY created_at DESC""")
        return _fetchall(cur)

def approve_nutritionist_request(request_id: int):
    with _conn() as cur:
        cur.execute("SELECT * FROM nutritionist_requests WHERE id=%s", (request_id,))
        req = _fetchone(cur)
        if not req:
            return
    code = _gen_studio_code()
    ret  = " RETURNING id" if USE_POSTGRES else ""
    with _conn() as cur:
        cur.execute(
            f"""INSERT INTO users
               (username,password_hash,nome,cognome,role,studio_code,
                sesso_nut,specializzazione,email_studio,telefono)
               VALUES (%s,%s,%s,%s,'nutritionist',%s,%s,%s,%s,%s){ret}""",
            (req["username"], req["password_hash"], req["nome"], req["cognome"],
             code, req["sesso_nut"], req["specializzazione"],
             req["email_studio"], req["telefono"])
        )
        cur.execute("UPDATE nutritionist_requests SET stato='Approvato' WHERE id=%s", (request_id,))

def reject_nutritionist_request(request_id: int, admin_note: str = ""):
    with _conn() as cur:
        cur.execute("UPDATE nutritionist_requests SET stato='Rifiutato', admin_note=%s WHERE id=%s",
                    (admin_note, request_id))

def get_all_nutritionist_requests() -> list:
    with _conn() as cur:
        cur.execute("SELECT * FROM nutritionist_requests ORDER BY created_at DESC")
        return _fetchall(cur)


# ==============================================================================
# ADMIN — gestione utenti (sospensione / eliminazione)
# ==============================================================================

def set_nutritionist_active(nut_id: int, active: bool):
    """Sospende (active=False) o riattiva (active=True) un nutrizionista."""
    with _conn() as cur:
        cur.execute("UPDATE users SET is_active=%s WHERE id=%s", (1 if active else 0, nut_id))

def delete_nutritionist_admin(nut_id: int):
    """Elimina un nutrizionista e tutti i suoi dati (CASCADE)."""
    with _conn() as cur:
        # Elimina in ordine per rispettare FK
        cur.execute("""DELETE FROM messages WHERE patient_id IN
            (SELECT id FROM patients WHERE nutritionist_id=%s)""", (nut_id,))
        cur.execute("""DELETE FROM diet_items WHERE plan_id IN
            (SELECT dp.id FROM diet_plans dp JOIN patients p ON p.id=dp.patient_id
             WHERE p.nutritionist_id=%s)""", (nut_id,))
        cur.execute("""DELETE FROM diet_plans WHERE patient_id IN
            (SELECT id FROM patients WHERE nutritionist_id=%s)""", (nut_id,))
        cur.execute("""DELETE FROM visits WHERE patient_id IN
            (SELECT id FROM patients WHERE nutritionist_id=%s)""", (nut_id,))
        cur.execute("DELETE FROM patients WHERE nutritionist_id=%s", (nut_id,))
        cur.execute("DELETE FROM appointments WHERE nutritionist_id=%s", (nut_id,))
        cur.execute("DELETE FROM templates WHERE nutritionist_id=%s", (nut_id,))
        cur.execute("DELETE FROM invite_tokens WHERE nutritionist_id=%s", (nut_id,))
        cur.execute("DELETE FROM patient_requests WHERE nutritionist_id=%s", (nut_id,))
        cur.execute("DELETE FROM bug_reports WHERE nutritionist_id=%s", (nut_id,))
        cur.execute("DELETE FROM users WHERE id=%s", (nut_id,))

def delete_patient_admin(patient_id: int):
    """Elimina un paziente e tutti i suoi dati."""
    with _conn() as cur:
        cur.execute("DELETE FROM messages WHERE patient_id=%s", (patient_id,))
        cur.execute("""DELETE FROM diet_items WHERE plan_id IN
            (SELECT id FROM diet_plans WHERE patient_id=%s)""", (patient_id,))
        cur.execute("DELETE FROM diet_plans WHERE patient_id=%s", (patient_id,))
        cur.execute("DELETE FROM visits WHERE patient_id=%s", (patient_id,))
        cur.execute("DELETE FROM patients WHERE id=%s", (patient_id,))


# ==============================================================================
# EMAIL — recupero credenziali
# ==============================================================================

def send_credentials_email(to_email: str, username: str, new_password: str,
                            app_url: str = "") -> tuple[bool, str]:
    """Invia email con username e nuova password tramite Brevo API HTTP.
    Richiede env: BREVO_API_KEY, SMTP_FROM."""
    import urllib.request
    import json as _json

    api_key   = os.environ.get("BREVO_API_KEY", "")
    smtp_from = os.environ.get("SMTP_FROM", "noreply@nutrinext.app")

    if not api_key:
        return False, "Servizio email non configurato. Contatta l'amministratore."

    body_text = f"""Ciao,

Hai richiesto il recupero delle credenziali di accesso a NutriNext.

Le tue credenziali aggiornate sono:

  Username:  {username}
  Password:  {new_password}

{"Puoi accedere all'app qui: " + app_url if app_url else ""}

Ti consigliamo di cambiare la password dopo il primo accesso.

Cordiali saluti,
Il team NutriNext
"""

    payload = _json.dumps({
        "sender":  {"name": "NutriNext", "email": smtp_from},
        "to":      [{"email": to_email}],
        "subject": "NutriNext — Recupero credenziali",
        "textContent": body_text
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key":      api_key,
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                return True, "Email inviata con successo."
            return False, f"Risposta Brevo: {resp.status}"
    except Exception as e:
        return False, f"Errore invio email: {e}"
