"""
Almacenamiento en SQLite.

Cumple dos funciones:
1. Historico y deduplicacion por Place ID (funciona con o sin Google Sheets).
2. Contador de requests a Places API por dia -> tope duro local (seccion 6).

Dos destinos, mismo SQL
-----------------------
- En local: el fichero de siempre, data/leads.db.
- Desplegado (Vercel u otro servidor sin disco persistente): Turso, que es
  SQLite alojado y habla el mismo dialecto. Se activa solo con poner
  TURSO_DATABASE_URL y TURSO_AUTH_TOKEN.

El resto del modulo no distingue entre los dos: `conectar()` devuelve un
objeto con la misma interfaz en ambos casos.
"""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from app import turso
from app.config import DIR_DATOS, settings
from app.models import Negocio

DB_PATH: Path = DIR_DATOS / "leads.db"

# El esquema se asegura una vez por proceso, no en cada import: contra Turso
# es un viaje de red, y hacerlo al importar dejaria la app sin arrancar si la
# base esta caida en ese instante.
_esquema_listo = False

ESQUEMA = """
CREATE TABLE IF NOT EXISTS negocios (
    place_id          TEXT PRIMARY KEY,
    nombre            TEXT,
    direccion         TEXT,
    telefono          TEXT,
    sitio_web         TEXT,
    categoria_google  TEXT,
    rating            REAL,
    resenas           INTEGER,
    maps_url          TEXT,
    email             TEXT DEFAULT '',
    estado_contacto   TEXT DEFAULT '',
    es_lead           INTEGER,
    motivo            TEXT,
    fecha_busqueda    TEXT,
    ciudad_buscada    TEXT,
    categoria_buscada TEXT,
    busqueda_id       TEXT
);
CREATE INDEX IF NOT EXISTS idx_busqueda ON negocios(busqueda_id);

CREATE TABLE IF NOT EXISTS uso_api (
    dia      TEXT PRIMARY KEY,
    requests INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS geocache (
    consulta TEXT PRIMARY KEY,
    lat      REAL,
    lng      REAL,
    etiqueta TEXT
);

-- Una campana = (ciudad + categoria). Recuerda que zonas ya se exploraron,
-- para que al repetir la busqueda manana se sigan trayendo negocios nuevos.
CREATE TABLE IF NOT EXISTS campanas (
    campana_id     TEXT PRIMARY KEY,
    ciudad         TEXT,
    categoria      TEXT,
    modo           TEXT,
    radio_km       REAL,
    radio_celda_km REAL,
    lat            REAL,
    lng            REAL,
    creada         TEXT,
    ultima_sesion  TEXT,
    total_celdas   INTEGER
);

CREATE TABLE IF NOT EXISTS celdas (
    campana_id  TEXT,
    indice      INTEGER,
    lat         REAL,
    lng         REAL,
    explorada   TEXT,             -- fecha, o NULL si sigue pendiente
    encontrados INTEGER DEFAULT 0,
    nuevos      INTEGER DEFAULT 0,
    PRIMARY KEY (campana_id, indice)
);
CREATE INDEX IF NOT EXISTS idx_celdas_pend
    ON celdas(campana_id, explorada, indice);

CREATE TABLE IF NOT EXISTS busquedas (
    busqueda_id TEXT PRIMARY KEY,
    fecha       TEXT,
    ciudad      TEXT,
    categoria   TEXT,
    radio_km    REAL,
    encontrados INTEGER,
    leads       INTEGER
);
"""


def _abrir():
    """Abre la conexion que toque segun la configuracion."""
    if settings.usa_turso:
        return turso.conectar(
            settings.turso_database_url, settings.turso_auth_token
        )
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # permite lecturas concurrentes
    return con


@contextmanager
def conectar():
    """
    Context manager que hace commit y CIERRA la conexion.

    Ojo: `with sqlite3.connect(...)` por si solo hace commit pero NO cierra,
    y con el servidor corriendo mucho tiempo las conexiones se acumulan y
    terminan dando "database is locked".
    """
    _asegurar_esquema()
    con = _abrir()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _asegurar_esquema() -> None:
    """Crea las tablas la primera vez que este proceso toca la base."""
    global _esquema_listo
    if _esquema_listo:
        return
    _esquema_listo = True     # antes de ejecutar, para no reintentar en bucle
    con = _abrir()
    try:
        con.executescript(ESQUEMA)
        con.commit()
    except Exception:
        _esquema_listo = False
        raise
    finally:
        con.close()


def init_db() -> None:
    _asegurar_esquema()


# ---------------------------------------------------------------- negocios
def place_ids_existentes() -> set[str]:
    with conectar() as con:
        return {fila[0] for fila in con.execute("SELECT place_id FROM negocios")}


def guardar_negocios(negocios: list[Negocio], busqueda_id: str) -> tuple[int, int]:
    """Inserta solo los Place IDs nuevos. Devuelve (nuevos, duplicados)."""
    existentes = place_ids_existentes()
    nuevos = [n for n in negocios if n.place_id not in existentes]
    duplicados = len(negocios) - len(nuevos)

    if nuevos:
        filas = [
            (
                n.place_id, n.nombre, n.direccion, n.telefono, n.sitio_web,
                n.categoria_google, n.rating, n.resenas, n.maps_url, n.email,
                n.estado_contacto, int(n.es_lead), n.motivo, n.fecha_busqueda,
                n.ciudad_buscada, n.categoria_buscada, busqueda_id,
            )
            for n in nuevos
        ]
        with conectar() as con:
            con.executemany(
                """INSERT OR IGNORE INTO negocios VALUES
                   (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                filas,
            )
    return len(nuevos), duplicados


def registrar_busqueda(
    busqueda_id: str, fecha: str, ciudad: str, categoria: str,
    radio_km: float, encontrados: int, leads: int,
) -> None:
    with conectar() as con:
        con.execute(
            "INSERT OR REPLACE INTO busquedas VALUES (?,?,?,?,?,?,?)",
            (busqueda_id, fecha, ciudad, categoria, radio_km, encontrados, leads),
        )


def historico(limite: int = 500, solo_leads: bool = False) -> list[dict]:
    sql = "SELECT * FROM negocios"
    if solo_leads:
        sql += " WHERE es_lead = 1"
    sql += " ORDER BY fecha_busqueda DESC LIMIT ?"
    with conectar() as con:
        return [dict(f) for f in con.execute(sql, (limite,))]


def listar_busquedas(limite: int = 50) -> list[dict]:
    with conectar() as con:
        return [
            dict(f)
            for f in con.execute(
                "SELECT * FROM busquedas ORDER BY fecha DESC LIMIT ?", (limite,)
            )
        ]


def negocios_de_busqueda(busqueda_id: str) -> list[dict]:
    with conectar() as con:
        return [
            dict(f)
            for f in con.execute(
                "SELECT * FROM negocios WHERE busqueda_id = ?", (busqueda_id,)
            )
        ]


# ------------------------------------------------------------- campanas
def id_campana(ciudad: str, categoria: str, modo: str) -> str:
    """Misma ciudad + categoria = misma campana, sin importar mayusculas."""
    semilla = f"{ciudad.strip().lower()}|{categoria.strip().lower()}|{modo}"
    return hashlib.sha1(semilla.encode("utf-8")).hexdigest()[:16]


def obtener_campana(campana_id: str) -> dict | None:
    with conectar() as con:
        fila = con.execute(
            "SELECT * FROM campanas WHERE campana_id = ?", (campana_id,)
        ).fetchone()
    return dict(fila) if fila else None


def crear_campana(
    campana_id: str, ciudad: str, categoria: str, modo: str,
    radio_km: float, radio_celda_km: float, lat: float, lng: float,
    celdas: list[tuple[float, float]], fecha: str,
) -> None:
    with conectar() as con:
        con.execute(
            "INSERT OR REPLACE INTO campanas VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (campana_id, ciudad, categoria, modo, radio_km, radio_celda_km,
             lat, lng, fecha, fecha, len(celdas)),
        )
        con.executemany(
            "INSERT OR IGNORE INTO celdas (campana_id, indice, lat, lng) "
            "VALUES (?,?,?,?)",
            [(campana_id, i, la, ln) for i, (la, ln) in enumerate(celdas)],
        )


def celdas_pendientes(campana_id: str, limite: int) -> list[dict]:
    """Siguientes zonas sin explorar, de dentro hacia afuera."""
    with conectar() as con:
        return [
            dict(f)
            for f in con.execute(
                "SELECT * FROM celdas WHERE campana_id = ? AND explorada IS NULL "
                "ORDER BY indice LIMIT ?",
                (campana_id, limite),
            )
        ]


def marcar_celda(
    campana_id: str, indice: int, fecha: str, encontrados: int, nuevos: int
) -> None:
    with conectar() as con:
        con.execute(
            "UPDATE celdas SET explorada = ?, encontrados = ?, nuevos = ? "
            "WHERE campana_id = ? AND indice = ?",
            (fecha, encontrados, nuevos, campana_id, indice),
        )
        con.execute(
            "UPDATE campanas SET ultima_sesion = ? WHERE campana_id = ?",
            (fecha, campana_id),
        )


def progreso_campana(campana_id: str) -> dict:
    with conectar() as con:
        fila = con.execute(
            "SELECT COUNT(*) AS total, "
            "       SUM(CASE WHEN explorada IS NOT NULL THEN 1 ELSE 0 END) AS hechas, "
            "       COALESCE(SUM(nuevos), 0) AS negocios_nuevos "
            "FROM celdas WHERE campana_id = ?",
            (campana_id,),
        ).fetchone()
    total = fila["total"] or 0
    hechas = fila["hechas"] or 0
    return {
        "total_celdas": total,
        "celdas_exploradas": hechas,
        "celdas_pendientes": total - hechas,
        "negocios_nuevos_acumulados": fila["negocios_nuevos"] or 0,
        "porcentaje": round(100 * hechas / total, 1) if total else 0.0,
        "terminada": total > 0 and hechas >= total,
    }


def listar_campanas(limite: int = 50) -> list[dict]:
    with conectar() as con:
        filas = [
            dict(f)
            for f in con.execute(
                "SELECT * FROM campanas ORDER BY ultima_sesion DESC LIMIT ?",
                (limite,),
            )
        ]
    for fila in filas:
        fila.update(progreso_campana(fila["campana_id"]))
    return filas


def reiniciar_campana(campana_id: str) -> int:
    """
    Vuelve a marcar todas las zonas como pendientes.

    Util meses despues, para recapturar negocios que abrieron desde entonces.
    Los Place IDs ya guardados siguen filtrandose, asi que no se duplica nada.
    """
    with conectar() as con:
        cursor = con.execute(
            "UPDATE celdas SET explorada = NULL WHERE campana_id = ?", (campana_id,)
        )
        return cursor.rowcount


# ------------------------------------------------- cache de geocodificacion
def geocache_leer(consulta: str) -> tuple[float, float, str] | None:
    """Evita pagar dos veces por geocodificar la misma ciudad."""
    with conectar() as con:
        fila = con.execute(
            "SELECT lat, lng, etiqueta FROM geocache WHERE consulta = ?",
            (consulta.strip().lower(),),
        ).fetchone()
    return (fila[0], fila[1], fila[2]) if fila else None


def ciudades_en_cache() -> list[str]:
    """Ciudades ya geocodificadas: buscarlas de nuevo no cuesta geocoding."""
    with conectar() as con:
        return [f[0] for f in con.execute("SELECT consulta FROM geocache")]


def geocache_guardar(consulta: str, lat: float, lng: float, etiqueta: str) -> None:
    with conectar() as con:
        con.execute(
            "INSERT OR REPLACE INTO geocache VALUES (?,?,?,?)",
            (consulta.strip().lower(), lat, lng, etiqueta),
        )


# ------------------------------------------------------------- cuota diaria
def requests_hoy() -> int:
    with conectar() as con:
        fila = con.execute(
            "SELECT requests FROM uso_api WHERE dia = ?", (date.today().isoformat(),)
        ).fetchone()
    return fila[0] if fila else 0


def sumar_requests(cantidad: int = 1) -> int:
    hoy = date.today().isoformat()
    with conectar() as con:
        con.execute(
            """INSERT INTO uso_api (dia, requests) VALUES (?, ?)
               ON CONFLICT(dia) DO UPDATE SET requests = requests + ?""",
            (hoy, cantidad, cantidad),
        )
        fila = con.execute("SELECT requests FROM uso_api WHERE dia = ?", (hoy,)).fetchone()
    return fila[0]
