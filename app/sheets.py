"""
Google Sheets como base de datos acumulativa (seccion 4).

Es OPCIONAL: si no hay credenciales configuradas, la app sigue funcionando
con SQLite local + exportacion a Excel/CSV. Nunca tumba una busqueda: si el
Sheet falla, se devuelve un aviso y los datos quedan igual guardados local.

Diseno: UNA sola hoja acumulativa con columna de fecha y de parametros, para
conservar el historico completo y poder deduplicar por Place ID facilmente.
"""
from app.config import settings
from app.models import Negocio

ENCABEZADOS = [
    "Fecha de busqueda",
    "Ciudad",
    "Categoria buscada",
    "Nombre del negocio",
    "Direccion",
    "Telefono",
    "Sitio web",
    "Es lead",
    "Motivo",
    "Rating",
    "Resenas",
    "Link Google Maps",
    "Email",
    "Estado de contacto",
    "Place ID",
]

COLUMNA_PLACE_ID = 15   # 1-indexada, debe coincidir con ENCABEZADOS
COLUMNA_TELEFONO = 6    # digitos pelados con indicativo, apta para formulas

# La columna P del Sheet ("Comentario") se llena a mano y el codigo no la toca.
# Es la primera que viene despues de ENCABEZADOS, asi que un valor de sobra en
# _fila() caeria justo encima de los comentarios escritos por el usuario.


class ErrorSheets(Exception):
    pass


def _fila(negocio: Negocio) -> list:
    """Los 15 valores de una fila, en el orden de ENCABEZADOS.

    Nunca puede devolver mas: lo que sobre se escribiria en la columna P, que
    es de comentarios escritos a mano.
    """
    return [
        negocio.fecha_busqueda,
        negocio.ciudad_buscada,
        negocio.categoria_buscada,
        negocio.nombre,
        negocio.direccion,
        negocio.telefono,
        negocio.sitio_web,
        "Si" if negocio.es_lead else "No",
        negocio.motivo,
        negocio.rating if negocio.rating is not None else "",
        negocio.resenas if negocio.resenas is not None else "",
        negocio.maps_url,
        negocio.email,
        negocio.estado_contacto,
        negocio.place_id,
    ]


def _abrir_hoja():
    import gspread
    from google.oauth2.service_account import Credentials

    # from_service_account_INFO (no _file): las credenciales llegan ya como
    # dict, vengan del JSON en disco o de la variable de entorno. Es la unica
    # via que funciona en un servidor sin disco propio, como Vercel.
    datos = settings.credenciales_sheets
    if datos is None:
        raise ErrorSheets(
            "No hay credenciales de service account utilizables: revisa "
            "GOOGLE_SERVICE_ACCOUNT_JSON (o GOOGLE_SERVICE_ACCOUNT_FILE)."
        )
    credenciales = Credentials.from_service_account_info(
        datos, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    cliente = gspread.authorize(credenciales)
    libro = cliente.open_by_key(settings.google_sheet_id)

    try:
        hoja = libro.worksheet(settings.google_sheet_tab)
    except Exception:
        hoja = libro.add_worksheet(
            title=settings.google_sheet_tab, rows=1000, cols=len(ENCABEZADOS)
        )

    # Asegurar encabezados (solo la primera vez)
    if not hoja.acell("A1").value:
        hoja.update(values=[ENCABEZADOS], range_name="A1")
        hoja.freeze(rows=1)
        hoja.format(f"A1:{chr(64 + len(ENCABEZADOS))}1", {"textFormat": {"bold": True}})

    return hoja


def place_ids_en_sheet(hoja) -> set[str]:
    valores = hoja.col_values(COLUMNA_PLACE_ID)
    return {v.strip() for v in valores[1:] if v.strip()}


def agregar_negocios(negocios: list[Negocio]) -> tuple[int, int, str]:
    """
    Escribe en el Sheet solo los Place IDs que aun no estan.
    Devuelve (agregados, duplicados_omitidos, aviso).
    """
    if settings.demo_mode:
        # Proteccion: en modo demo los negocios son inventados. Escribirlos en
        # el Sheet real ensuciaria datos de verdad y habria que borrarlos a mano.
        return 0, 0, (
            "MODO DEMO: no se escribio nada en Google Sheets (los datos de "
            "ejemplo no deben mezclarse con tus leads reales)."
        )

    if not settings.sheets_habilitado:
        return 0, 0, (
            "Google Sheets no esta configurado: los datos quedaron guardados "
            "localmente y puedes descargarlos en Excel/CSV."
        )

    try:
        hoja = _abrir_hoja()
        existentes = place_ids_en_sheet(hoja)
        nuevos = [n for n in negocios if n.place_id not in existentes]
        duplicados = len(negocios) - len(nuevos)

        if nuevos:
            hoja.append_rows(
                [_fila(n) for n in nuevos],
                value_input_option="USER_ENTERED",
            )
        return len(nuevos), duplicados, ""
    except (FileNotFoundError, ErrorSheets) as exc:
        return 0, 0, (
            f"Credenciales de Google Sheets no utilizables: {exc}"
            if isinstance(exc, ErrorSheets)
            else "No se encontro el archivo de credenciales indicado en "
                 "GOOGLE_SERVICE_ACCOUNT_FILE."
        )
    except Exception as exc:  # nunca tumbar la busqueda por culpa del Sheet
        return 0, 0, (
            f"No se pudo escribir en Google Sheets ({type(exc).__name__}: {exc}). "
            "Revisa que hayas compartido el Sheet con el email de la service "
            "account como Editor. Los datos si quedaron guardados localmente."
        )


# ------------------------------------------------------------------- CRM
# Puente entre el Google Sheet y la pagina de seguimiento.
#
# Reparto de columnas, y el motivo de cada una:
#   N  Estado de contacto   lo escribe el CRM
#   P  Comentario           TUYO. Se lee al importar, jamas se escribe.
#   Q  Ultimo comentario    lo escribe el CRM
#
# El comentario del CRM va a Q y no a P justamente para no pisar las notas
# que ya habias escrito a mano en P. Son dos columnas distintas a proposito.
COLUMNA_ESTADO = 14          # N
COLUMNA_COMENTARIO = 16      # P, solo lectura
COLUMNA_COMENTARIO_CRM = 17  # Q

ENCABEZADO_COMENTARIO_CRM = "Ultimo comentario (seguimiento)"

_INDICE_ESTADO = COLUMNA_ESTADO - 1
_INDICE_PLACE_ID = COLUMNA_PLACE_ID - 1
_INDICE_COMENTARIO = COLUMNA_COMENTARIO - 1
_INDICE_COMENTARIO_CRM = COLUMNA_COMENTARIO_CRM - 1

# El encabezado de Q viaja en cada escritura. Reescribir el mismo texto no
# cuesta nada y evita una lectura extra solo para comprobar si ya estaba.
_CABECERA_Q = {"range": "Q1", "values": [[ENCABEZADO_COMENTARIO_CRM]]}


def _celda(fila: list, indice: int) -> str:
    """Valor de una celda tolerando filas cortas (Sheets recorta las vacias)."""
    return fila[indice].strip() if len(fila) > indice else ""


def leer_seguimiento_manual() -> tuple[list[dict], str]:
    """
    Lo que ya estaba escrito a mano en el Sheet: estado (N) y comentario (P).

    Devuelve (filas, aviso). Solo lectura, asi que no puede estropear nada.
    """
    if not settings.sheets_habilitado:
        return [], (
            "Google Sheets no esta configurado, asi que no hay nada que "
            "importar. El seguimiento funciona igual sin el."
        )
    try:
        hoja = _abrir_hoja()
        filas = hoja.get_all_values()
    except Exception as exc:
        return [], f"No se pudo leer el Google Sheet ({type(exc).__name__}: {exc})."

    recogidas = []
    for fila in filas[1:]:                       # la primera son encabezados
        place_id = _celda(fila, _INDICE_PLACE_ID)
        if not place_id:
            continue
        estado = _celda(fila, _INDICE_ESTADO)
        comentario = _celda(fila, _INDICE_COMENTARIO)
        if estado or comentario:
            recogidas.append(
                {"place_id": place_id, "estado": estado, "comentario": comentario}
            )
    return recogidas, ""


def _asegurar_columna_crm(hoja) -> None:
    """Crea la columna Q si la hoja todavia no llega hasta ahi.

    El Sheet nacio con 16 columnas (hasta la P) y escribir en la Q sin
    ensancharlo antes devuelve "Range exceeds grid limits". `col_count` ya
    viene en los metadatos de la hoja, asi que comprobarlo no cuesta otra
    llamada.
    """
    if hoja.col_count < COLUMNA_COMENTARIO_CRM:
        hoja.resize(cols=COLUMNA_COMENTARIO_CRM)


def _filas_por_place_id(hoja) -> dict:
    """place_id -> numero de fila en el Sheet. Una sola lectura de la columna O."""
    numeros = {}
    for numero, valor in enumerate(hoja.col_values(COLUMNA_PLACE_ID), start=1):
        limpio = valor.strip()
        if limpio and limpio not in numeros:
            numeros[limpio] = numero
    return numeros


def escribir_seguimiento(datos: dict) -> tuple[int, str]:
    """
    Vuelca estado y ultimo comentario al Sheet.

    `datos` es place_id -> (estado legible, comentario). Escribe solo las
    celdas que cambian, en un unico batch, y nunca toca la columna P.
    Devuelve (celdas escritas, aviso).
    """
    if settings.demo_mode:
        return 0, "MODO DEMO: no se escribio nada en Google Sheets."
    if not settings.sheets_habilitado:
        return 0, "Google Sheets no esta configurado."
    if not datos:
        return 0, "No hay seguimiento que volcar todavia."

    try:
        hoja = _abrir_hoja()
        _asegurar_columna_crm(hoja)
        filas = hoja.get_all_values()
        cambios = []
        for numero, fila in enumerate(filas[1:], start=2):
            nuevo = datos.get(_celda(fila, _INDICE_PLACE_ID))
            if nuevo is None:
                continue
            estado, comentario = nuevo
            if estado and _celda(fila, _INDICE_ESTADO) != estado:
                cambios.append({"range": f"N{numero}", "values": [[estado]]})
            if comentario and _celda(fila, _INDICE_COMENTARIO_CRM) != comentario:
                cambios.append({"range": f"Q{numero}", "values": [[comentario]]})

        if cambios:
            hoja.batch_update(
                [_CABECERA_Q] + cambios, value_input_option="USER_ENTERED"
            )
        return len(cambios), ""
    except Exception as exc:
        return 0, (
            f"No se pudo escribir en Google Sheets ({type(exc).__name__}: {exc}). "
            "El seguimiento sigue guardado en la base de datos."
        )


def escribir_seguimiento_de_uno(
    place_id: str, estado: str, comentario: str
) -> str:
    """
    Lleva al Sheet el estado y el comentario de UN cliente, recien guardado.

    Se llama despues de cada anotacion, no antes: la base de datos ya tiene el
    dato, asi que si el Sheet falla solo se pierde el reflejo, nunca el
    seguimiento. Devuelve el aviso, o cadena vacia si todo fue bien.

    Son dos llamadas a la API de Sheets (leer la columna de Place ID y
    escribir la fila). La API no cobra; lo unico que cuesta es la espera, y
    por eso se puede apagar con CRM_SYNC_SHEET.
    """
    if settings.demo_mode or not settings.sheets_habilitado:
        return ""
    try:
        hoja = _abrir_hoja()
        _asegurar_columna_crm(hoja)
        numero = _filas_por_place_id(hoja).get(place_id)
        if numero is None:
            return (
                "Guardado. Ese negocio todavia no tiene fila en el Google "
                "Sheet, asi que el comentario solo quedo en la base de datos."
            )
        cambios = [_CABECERA_Q, {"range": f"N{numero}", "values": [[estado]]}]
        if comentario:
            cambios.append({"range": f"Q{numero}", "values": [[comentario]]})
        hoja.batch_update(cambios, value_input_option="USER_ENTERED")
        return ""
    except Exception as exc:
        return (
            f"Guardado en la base de datos, pero no se pudo reflejar en el "
            f"Google Sheet ({type(exc).__name__}: {exc})."
        )
