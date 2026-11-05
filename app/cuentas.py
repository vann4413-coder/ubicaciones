"""Cuentas de usuario, sesiones, compras sueltas y uso de la suscripción (SQLite).

En Railway la base de datos debe estar en un volumen persistente (UBI_DB=/data/ubicaciones.db);
si no, se perdería en cada despliegue.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app import config

RUTA_DB = Path(os.getenv("UBI_DB", str(config.DATOS_DIR / "ubicaciones.db")))
SECRETO = (os.getenv("UBI_SECRETO") or secrets.token_hex(32)).encode()
ADMIN = {e.strip().lower() for e in os.getenv("UBI_ADMIN_EMAILS", "").split(",") if e.strip()}
DURACION_SESION = 60 * 60 * 24 * 30  # 30 días
LIMITES = {"profesional": 50, "premium": None}  # informes al mes (None = ilimitado)

_lock = threading.Lock()
_con: sqlite3.Connection | None = None

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, hash TEXT NOT NULL, creado TEXT NOT NULL,
  stripe_customer TEXT, plan TEXT, plan_estado TEXT, suscripcion TEXT, periodo_fin INTEGER
);
CREATE TABLE IF NOT EXISTS uso (
  usuario_id INTEGER NOT NULL, rc TEXT NOT NULL, mes TEXT NOT NULL, fecha TEXT NOT NULL,
  PRIMARY KEY (usuario_id, rc, mes)
);
CREATE TABLE IF NOT EXISTS compras (
  session_id TEXT PRIMARY KEY, rc TEXT NOT NULL, email TEXT, importe INTEGER, fecha TEXT NOT NULL,
  token TEXT NOT NULL, usuario_id INTEGER
);
"""


def db() -> sqlite3.Connection:
    global _con
    if _con is None:
        RUTA_DB.parent.mkdir(parents=True, exist_ok=True)
        _con = sqlite3.connect(str(RUTA_DB), check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.executescript(ESQUEMA)
    return _con


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mes() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ---------- Contraseñas y sesiones ----------

def _hash(clave: str, sal: bytes | None = None) -> str:
    sal = sal or secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=2**14, r=8, p=1)
    return sal.hex() + "$" + h.hex()


def _verificar(clave: str, guardado: str) -> bool:
    sal, h = guardado.split("$")
    return hmac.compare_digest(_hash(clave, bytes.fromhex(sal)).split("$")[1], h)


def firmar(valor: str) -> str:
    return valor + "." + hmac.new(SECRETO, valor.encode(), hashlib.sha256).hexdigest()[:32]


def comprobar_firma(firmado: str | None) -> str | None:
    if not firmado or "." not in firmado:
        return None
    valor, _ = firmado.rsplit(".", 1)
    return valor if hmac.compare_digest(firmar(valor), firmado) else None


def cookie_sesion(usuario_id: int) -> str:
    return firmar(f"{usuario_id}:{int(time.time()) + DURACION_SESION}")


def usuario_de_cookie(cookie: str | None) -> dict | None:
    valor = comprobar_firma(cookie)
    if not valor:
        return None
    uid, caduca = valor.split(":")
    if int(caduca) < time.time():
        return None
    return obtener(int(uid))


# ---------- Usuarios ----------

def registrar(email: str, clave: str) -> dict:
    email = email.strip().lower()
    if "@" not in email or len(clave) < 8:
        raise ValueError("Correo no válido o contraseña de menos de 8 caracteres.")
    with _lock:
        try:
            cur = db().execute("INSERT INTO usuarios (email, hash, creado) VALUES (?, ?, ?)", (email, _hash(clave), _ahora()))
            db().commit()
        except sqlite3.IntegrityError:
            raise ValueError("Ya existe una cuenta con ese correo. Inicia sesión.") from None
    return obtener(cur.lastrowid)


def entrar(email: str, clave: str) -> dict | None:
    fila = db().execute("SELECT * FROM usuarios WHERE email = ?", (email.strip().lower(),)).fetchone()
    return dict(fila) if fila and _verificar(clave, fila["hash"]) else None


def obtener(uid: int) -> dict | None:
    fila = db().execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    return dict(fila) if fila else None


def por_email(email: str) -> dict | None:
    fila = db().execute("SELECT * FROM usuarios WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    return dict(fila) if fila else None


def por_customer(customer: str) -> dict | None:
    fila = db().execute("SELECT * FROM usuarios WHERE stripe_customer = ?", (customer,)).fetchone()
    return dict(fila) if fila else None


def actualizar_plan(uid: int, **campos) -> None:
    permitidos = {"stripe_customer", "plan", "plan_estado", "suscripcion", "periodo_fin"}
    sets = {k: v for k, v in campos.items() if k in permitidos}
    if not sets:
        return
    with _lock:
        db().execute(f"UPDATE usuarios SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), uid))
        db().commit()


# ---------- Derechos de acceso ----------

def es_admin(usuario: dict | None) -> bool:
    return bool(usuario and usuario["email"] in ADMIN)


def plan_activo(usuario: dict | None) -> str | None:
    if not usuario:
        return None
    if es_admin(usuario):
        return "premium"
    if usuario.get("plan") in LIMITES and usuario.get("plan_estado") in ("active", "trialing"):
        return usuario["plan"]
    return None


def usados_mes(uid: int) -> int:
    return db().execute("SELECT COUNT(*) FROM uso WHERE usuario_id = ? AND mes = ?", (uid, _mes())).fetchone()[0]


def ya_usado(uid: int, rc: str) -> bool:
    return db().execute("SELECT 1 FROM uso WHERE usuario_id = ? AND rc = ? AND mes = ?", (uid, rc, _mes())).fetchone() is not None


def puede_ver_con_plan(usuario: dict | None, rc: str) -> bool:
    plan = plan_activo(usuario)
    if not plan:
        return False
    limite = LIMITES[plan]
    return limite is None or ya_usado(usuario["id"], rc) or usados_mes(usuario["id"]) < limite


def registrar_uso(usuario: dict, rc: str) -> None:
    with _lock:
        db().execute("INSERT OR IGNORE INTO uso (usuario_id, rc, mes, fecha) VALUES (?, ?, ?, ?)", (usuario["id"], rc, _mes(), _ahora()))
        db().commit()


def historial(uid: int, limite: int = 50) -> list[dict]:
    filas = db().execute("SELECT rc, MAX(fecha) AS fecha FROM uso WHERE usuario_id = ? GROUP BY rc ORDER BY fecha DESC LIMIT ?", (uid, limite))
    compras = db().execute("SELECT rc, fecha FROM compras WHERE usuario_id = ? ORDER BY fecha DESC LIMIT ?", (uid, limite))
    vistos, salida = set(), []
    for f in [*filas, *compras]:
        if f["rc"] not in vistos:
            vistos.add(f["rc"])
            salida.append({"rc": f["rc"], "fecha": f["fecha"][:10]})
    return salida


# ---------- Compras sueltas ----------

def token_compra(rc: str, session_id: str) -> str:
    return hmac.new(SECRETO, f"{rc}|{session_id}".encode(), hashlib.sha256).hexdigest()[:24]


def guardar_compra(session_id: str, rc: str, email: str, importe: int, usuario_id: int | None) -> str:
    token = token_compra(rc, session_id)
    with _lock:
        db().execute("INSERT OR IGNORE INTO compras (session_id, rc, email, importe, fecha, token, usuario_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (session_id, rc, email, importe, _ahora(), token, usuario_id))
        db().commit()
    return token


def compra_valida(rc: str, token: str | None) -> bool:
    if not token:
        return False
    return db().execute("SELECT 1 FROM compras WHERE rc = ? AND token = ?", (rc, token)).fetchone() is not None


def compra_de_usuario(uid: int, rc: str) -> bool:
    return db().execute("SELECT 1 FROM compras WHERE rc = ? AND usuario_id = ?", (rc, uid)).fetchone() is not None
