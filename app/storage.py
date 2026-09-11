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
import re
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

-- ------------------------------------------------------------- CRM
-- Seguimiento comercial. Vive en tablas aparte y NO dentro de `negocios`
-- a proposito: las altas de negocios usan INSERT OR IGNORE con una tupla
-- posicional, asi que anadir columnas ahi romperia la insercion. Ademas el
-- scraping y la gestion de clientes cambian por motivos distintos.
CREATE TABLE IF NOT EXISTS seguimiento (
    place_id        TEXT PRIMARY KEY,
    estado          TEXT NOT NULL DEFAULT 'sin_contactar',
    responsable     TEXT DEFAULT '',
    proximo_paso    TEXT DEFAULT '',   -- fecha ISO: cuando volver a insistir
    ultimo_contacto TEXT DEFAULT '',
    ultimo_canal    TEXT DEFAULT '',
    intentos        INTEGER NOT NULL DEFAULT 0,
    comentario      TEXT DEFAULT '',   -- ultimo comentario, para la lista
    actualizado     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_seg_estado ON seguimiento(estado);
CREATE INDEX IF NOT EXISTS idx_seg_proximo ON seguimiento(proximo_paso);

-- Bitacora: una fila por cada llamada, WhatsApp, correo o nota. Nunca se
-- borra ni se edita, para que el historial de un cliente sea fiable.
CREATE TABLE IF NOT EXISTS interacciones (
    id           TEXT PRIMARY KEY,
    place_id     TEXT NOT NULL,
    fecha        TEXT,
    canal        TEXT,
    estado_nuevo TEXT,
    comentario   TEXT,
    proximo_paso TEXT,
    autor        TEXT
);
CREATE INDEX IF NOT EXISTS idx_inter_place ON interacciones(place_id, fecha);

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


# --------------------------------------------------------------------- CRM
# Consultas de la pagina de seguimiento de clientes. El vocabulario (que
# estados existen, que canales) vive en app/crm.py; aqui solo hay SQL.

ESTADO_INICIAL = "sin_contactar"

# Un negocio sin fila en seguimiento cuenta como "sin contactar". Se resuelve
# con LEFT JOIN + COALESCE en vez de crear filas vacias para los 3.700
# negocios: asi el CRM funciona sobre lo que ya hay, sin migrar nada.
_SELECT_CRM = """
SELECT n.place_id, n.nombre, n.direccion, n.telefono, n.sitio_web,
       n.categoria_google, n.rating, n.resenas, n.maps_url, n.email,
       n.es_lead, n.motivo, n.fecha_busqueda, n.ciudad_buscada,
       n.categoria_buscada,
       COALESCE(s.estado, 'sin_contactar') AS estado,
       COALESCE(s.responsable, '')         AS responsable,
       COALESCE(s.proximo_paso, '')        AS proximo_paso,
       COALESCE(s.ultimo_contacto, '')     AS ultimo_contacto,
       COALESCE(s.ultimo_canal, '')        AS ultimo_canal,
       COALESCE(s.intentos, 0)             AS intentos,
       COALESCE(s.comentario, '')          AS comentario,
       COALESCE(s.actualizado, '')         AS actualizado
FROM negocios n
LEFT JOIN seguimiento s ON s.place_id = n.place_id
"""

# La normalizacion a digitos pelados se anadio despues de las primeras
# campanas, asi que en la base conviven "573127217006" y "312 7217006". Los
# filtros limpian la columna al vuelo en vez de reescribir el historico: el
# proyecto no actualiza negocios ya guardados.
_TEL_LIMPIO = (
    "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
    "COALESCE(n.telefono, ''), ' ', ''), '-', ''), '(', ''), ')', ''), '+', ''), '.', '')"
)

# Celular colombiano: 57 + 3xxxxxxxxx, o los 10 digitos sin indicativo que
# devuelve Google cuando da el numero en formato nacional. Importa porque
# WhatsApp solo funciona contra moviles.
_ES_CELULAR = (
    f"(({_TEL_LIMPIO} LIKE '573%' AND LENGTH({_TEL_LIMPIO}) = 12)"
    f" OR ({_TEL_LIMPIO} LIKE '3%' AND LENGTH({_TEL_LIMPIO}) = 10))"
)

_ORDENES = {
    # Primero los leads y, dentro de ellos, los negocios mas establecidos:
    # son los que mas sentido tiene llamar antes.
    "relevancia": "ORDER BY n.es_lead DESC, COALESCE(n.resenas, 0) DESC, n.nombre",
    "nombre":     "ORDER BY n.nombre COLLATE NOCASE",
    "reciente":   "ORDER BY COALESCE(s.actualizado, '') DESC, n.nombre",
    "proximo":    ("ORDER BY CASE WHEN COALESCE(s.proximo_paso, '') = '' THEN 1 "
                   "ELSE 0 END, s.proximo_paso, n.nombre"),
    "intentos":   "ORDER BY COALESCE(s.intentos, 0) DESC, n.nombre",
}


def _where_crm(filtros: dict) -> tuple[str, list]:
    """Traduce los filtros de la pagina a un WHERE con sus parametros."""
    condiciones: list[str] = []
    args: list = []

    texto = (filtros.get("texto") or "").strip()
    if texto:
        patron = f"%{texto}%"
        # El telefono se busca contra la version limpia, para que escribir
        # "3127217006" encuentre tanto "573127217006" como "312 7217006".
        digitos = re.sub(r"\D+", "", texto)
        patron_tel = f"%{digitos}%" if digitos else patron
        condiciones.append(
            f"(n.nombre LIKE ? OR n.direccion LIKE ? OR {_TEL_LIMPIO} LIKE ?)"
        )
        args += [patron, patron, patron_tel]

    for campo, columna in (
        ("categoria", "n.categoria_buscada"),
        ("ciudad", "n.ciudad_buscada"),
        ("responsable", "COALESCE(s.responsable, '')"),
    ):
        valor = (filtros.get(campo) or "").strip()
        if valor:
            condiciones.append(f"{columna} = ?")
            args.append(valor)

    estados = filtros.get("estados") or []
    if estados:
        huecos = ",".join("?" for _ in estados)
        condiciones.append(f"COALESCE(s.estado, 'sin_contactar') IN ({huecos})")
        args += list(estados)

    contactado = filtros.get("contactado")
    if contactado == "no":
        condiciones.append("COALESCE(s.estado, 'sin_contactar') = 'sin_contactar'")
    elif contactado == "si":
        condiciones.append("COALESCE(s.estado, 'sin_contactar') <> 'sin_contactar'")

    es_lead = filtros.get("es_lead")
    if es_lead == "si":
        condiciones.append("n.es_lead = 1")
    elif es_lead == "no":
        condiciones.append("n.es_lead = 0")

    telefono = filtros.get("telefono")
    if telefono == "con":
        condiciones.append(f"{_TEL_LIMPIO} <> ''")
    elif telefono == "sin":
        condiciones.append(f"{_TEL_LIMPIO} = ''")
    elif telefono == "celular":
        condiciones.append(_ES_CELULAR)
    elif telefono == "fijo":
        condiciones.append(f"{_TEL_LIMPIO} <> '' AND NOT {_ES_CELULAR}")

    if filtros.get("agenda_hasta"):
        condiciones.append(
            "COALESCE(s.proximo_paso, '') <> '' AND s.proximo_paso <= ?"
        )
        args.append(filtros["agenda_hasta"])

    if not condiciones:
        return "", args
    return " WHERE " + " AND ".join(condiciones), args


def crm_listar(
    filtros: dict, limite: int = 100, desplazamiento: int = 0,
    orden: str = "relevancia",
) -> tuple[list[dict], int]:
    """Devuelve (filas de esta pagina, total que cumple el filtro)."""
    where, args = _where_crm(filtros)
    orden_sql = _ORDENES.get(orden, _ORDENES["relevancia"])
    sql = f"{_SELECT_CRM}{where} {orden_sql} LIMIT ? OFFSET ?"
    conteo = (
        "SELECT COUNT(*) FROM negocios n "
        "LEFT JOIN seguimiento s ON s.place_id = n.place_id" + where
    )
    with conectar() as con:
        filas = [dict(f) for f in con.execute(sql, (*args, limite, desplazamiento))]
        total = con.execute(conteo, args).fetchone()[0]
    return filas, total


def crm_cliente(place_id: str) -> dict | None:
    with conectar() as con:
        fila = con.execute(
            f"{_SELECT_CRM} WHERE n.place_id = ?", (place_id,)
        ).fetchone()
    return dict(fila) if fila else None


def crm_interacciones(place_id: str, limite: int = 200) -> list[dict]:
    with conectar() as con:
        return [
            dict(f)
            for f in con.execute(
                "SELECT * FROM interacciones WHERE place_id = ? "
                "ORDER BY fecha DESC LIMIT ?",
                (place_id, limite),
            )
        ]


def crm_guardar_interaccion(
    interaccion_id: str, place_id: str, fecha: str, canal: str,
    estado: str, comentario: str, proximo_paso: str, responsable: str,
    cuenta_intento: bool,
) -> None:
    """
    Anota la interaccion en la bitacora y deja el seguimiento al dia.

    Son dos escrituras seguidas, no una transaccion: contra Turso cada
    sentencia viaja sola y se autoconfirma. Con una sola persona llamando por
    telefono no hay carrera posible, y el orden elegido (primero la bitacora)
    hace que el peor caso sea una interaccion registrada sin resumen, nunca un
    resumen sin respaldo en el historial.

    ultimo_contacto y ultimo_canal solo se tocan cuando hubo un intento real:
    una nota interna no cuenta como haber llamado.
    """
    with conectar() as con:
        con.execute(
            "INSERT INTO interacciones VALUES (?,?,?,?,?,?,?,?)",
            (interaccion_id, place_id, fecha, canal, estado, comentario,
             proximo_paso, responsable),
        )
        con.execute(
            """INSERT INTO seguimiento (place_id, estado, responsable,
                   proximo_paso, ultimo_contacto, ultimo_canal, intentos,
                   comentario, actualizado)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(place_id) DO UPDATE SET
                   estado          = excluded.estado,
                   responsable     = excluded.responsable,
                   proximo_paso    = excluded.proximo_paso,
                   ultimo_contacto = CASE WHEN excluded.ultimo_contacto <> ''
                                          THEN excluded.ultimo_contacto
                                          ELSE seguimiento.ultimo_contacto END,
                   ultimo_canal    = CASE WHEN excluded.ultimo_contacto <> ''
                                          THEN excluded.ultimo_canal
                                          ELSE seguimiento.ultimo_canal END,
                   intentos        = seguimiento.intentos + ?,
                   comentario      = CASE WHEN excluded.comentario <> ''
                                          THEN excluded.comentario
                                          ELSE seguimiento.comentario END,
                   actualizado     = excluded.actualizado""",
            (
                place_id, estado, responsable, proximo_paso,
                fecha if cuenta_intento else "",
                canal if cuenta_intento else "",
                1 if cuenta_intento else 0,
                comentario, fecha,
                1 if cuenta_intento else 0,
            ),
        )


def crm_resumen() -> dict:
    """Cuantos negocios hay en cada estado. Una sola consulta."""
    with conectar() as con:
        filas = con.execute(
            "SELECT COALESCE(s.estado, 'sin_contactar') AS estado, "
            "       COUNT(*) AS cantidad "
            "FROM negocios n "
            "LEFT JOIN seguimiento s ON s.place_id = n.place_id "
            "GROUP BY COALESCE(s.estado, 'sin_contactar')"
        )
        return {f["estado"]: f["cantidad"] for f in filas}


def crm_agenda(hasta: str) -> int:
    """Cuantos clientes tienen un proximo paso vencido o para hoy."""
    with conectar() as con:
        fila = con.execute(
            "SELECT COUNT(*) FROM seguimiento "
            "WHERE proximo_paso <> '' AND proximo_paso <= ?",
            (hasta,),
        ).fetchone()
    return fila[0] or 0


def crm_valores_distintos() -> dict:
    """Categorias, ciudades y responsables que existen, para los desplegables."""
    with conectar() as con:
        categorias = [
            f[0] for f in con.execute(
                "SELECT DISTINCT categoria_buscada FROM negocios "
                "WHERE COALESCE(categoria_buscada, '') <> '' "
                "ORDER BY categoria_buscada"
            )
        ]
        ciudades = [
            f[0] for f in con.execute(
                "SELECT DISTINCT ciudad_buscada FROM negocios "
                "WHERE COALESCE(ciudad_buscada, '') <> '' "
                "ORDER BY ciudad_buscada"
            )
        ]
        responsables = [
            f[0] for f in con.execute(
                "SELECT DISTINCT responsable FROM seguimiento "
                "WHERE COALESCE(responsable, '') <> '' ORDER BY responsable"
            )
        ]
    return {
        "categorias": categorias,
        "ciudades": ciudades,
        "responsables": responsables,
    }


def crm_estados_actuales() -> dict:
    """place_id -> estado. Se usa para saber a quien ya se toco."""
    with conectar() as con:
        return {
            f["place_id"]: f["estado"]
            for f in con.execute("SELECT place_id, estado FROM seguimiento")
        }


def crm_seguimiento_completo() -> dict:
    """place_id -> {estado, comentario}, para volcarlo al Google Sheet."""
    with conectar() as con:
        return {
            f["place_id"]: {"estado": f["estado"], "comentario": f["comentario"] or ""}
            for f in con.execute(
                "SELECT place_id, estado, comentario FROM seguimiento"
            )
        }


def crm_sembrar(filas: list[tuple]) -> int:
    """
    Alta masiva de seguimiento sin pisar lo que ya existe.

    Se usa al importar lo que ya estaba escrito a mano en el Google Sheet.
    INSERT OR IGNORE: si el cliente ya tiene seguimiento en la app, manda la
    app, porque es el dato mas reciente.
    """
    if not filas:
        return 0
    antes = len(crm_estados_actuales())
    with conectar() as con:
        con.executemany(
            """INSERT OR IGNORE INTO seguimiento (place_id, estado, responsable,
                   proximo_paso, ultimo_contacto, ultimo_canal, intentos,
                   comentario, actualizado)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            filas,
        )
    return len(crm_estados_actuales()) - antes


def crm_place_ids_conocidos() -> set:
    with conectar() as con:
        return {f[0] for f in con.execute("SELECT place_id FROM negocios")}
