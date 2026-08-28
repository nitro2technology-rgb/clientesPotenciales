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

COLUMNA_PLACE_ID = 15  # 1-indexada, debe coincidir con ENCABEZADOS


class ErrorSheets(Exception):
    pass


def _fila(negocio: Negocio) -> list:
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
