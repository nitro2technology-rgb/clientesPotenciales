"""
Seguimiento comercial de los leads (la pagina /crm).

Que resuelve
------------
Los negocios los encuentra el buscador; a partir de ahi hay que llamarlos uno
a uno y recordar que paso con cada uno. Este modulo pone el vocabulario de ese
trabajo (que estados existen, que canales de contacto) y las operaciones de
alto nivel. El SQL vive en storage.py, como el resto de la app.

Regla de oro: NADA se edita en silencio. Cada cambio de estado deja una fila
en `interacciones`, asi que el historial de un cliente siempre explica como
llego a donde esta.
"""
import unicodedata
import uuid
from datetime import date

from app import storage
from app.models import ahora_iso, solo_digitos

# ---------------------------------------------------------------- estados
# grupo: sirve para los filtros rapidos y para agrupar el desplegable.
#   pendiente -> todavia hay que hacer algo
#   proceso   -> la conversacion esta viva
#   cerrado   -> no hay mas que hacer, para bien o para mal
ESTADOS = [
    {"clave": "sin_contactar",   "etiqueta": "Sin contactar",     "grupo": "pendiente", "tono": "gris"},
    {"clave": "no_contesta",     "etiqueta": "No contesto",       "grupo": "pendiente", "tono": "ambar"},
    {"clave": "volver_a_llamar", "etiqueta": "Volver a llamar",   "grupo": "pendiente", "tono": "ambar"},
    {"clave": "pidio_info",      "etiqueta": "Pidio informacion", "grupo": "proceso",   "tono": "azul"},
    {"clave": "contactado",      "etiqueta": "Contactado",        "grupo": "proceso",   "tono": "azul"},
    {"clave": "info_enviada",    "etiqueta": "Info enviada",      "grupo": "proceso",   "tono": "azul"},
    {"clave": "interesado",      "etiqueta": "Interesado",        "grupo": "proceso",   "tono": "verde"},
    {"clave": "cliente",         "etiqueta": "Cliente cerrado",   "grupo": "cerrado",   "tono": "verde"},
    {"clave": "finalizado",      "etiqueta": "Finalizado",        "grupo": "cerrado",   "tono": "gris"},
    {"clave": "no_interesa",     "etiqueta": "No le interesa",    "grupo": "cerrado",   "tono": "rojo"},
    {"clave": "numero_malo",     "etiqueta": "Numero equivocado", "grupo": "cerrado",   "tono": "rojo"},
]

CLAVES_ESTADO = {e["clave"] for e in ESTADOS}
ETIQUETA_ESTADO = {e["clave"]: e["etiqueta"] for e in ESTADOS}
ESTADOS_POR_GRUPO = {
    grupo: [e["clave"] for e in ESTADOS if e["grupo"] == grupo]
    for grupo in ("pendiente", "proceso", "cerrado")
}

# ---------------------------------------------------------------- canales
# "nota" es distinto de los demas: escribir una nota no es haber intentado
# contactar, asi que no suma intento ni mueve la fecha de ultimo contacto.
CANALES = [
    {"clave": "llamada",    "etiqueta": "Llamada"},
    {"clave": "whatsapp",   "etiqueta": "WhatsApp"},
    {"clave": "correo",     "etiqueta": "Correo"},
    {"clave": "presencial", "etiqueta": "Visita"},
    {"clave": "nota",       "etiqueta": "Nota interna"},
]

CLAVES_CANAL = {c["clave"] for c in CANALES}
CANAL_SIN_INTENTO = "nota"

ORDENES = [
    {"clave": "relevancia", "etiqueta": "Leads primero"},
    {"clave": "proximo",    "etiqueta": "Proximo paso mas cercano"},
    {"clave": "reciente",   "etiqueta": "Movido mas recientemente"},
    {"clave": "intentos",   "etiqueta": "Mas intentos"},
    {"clave": "nombre",     "etiqueta": "Nombre A-Z"},
]

MAX_POR_PAGINA = 500


class ErrorCRM(Exception):
    """Dato de entrada invalido. main.py lo traduce a un 400."""


# ------------------------------------------------------------- telefonos
def es_celular(telefono: str) -> bool:
    """
    True si el numero admite WhatsApp.

    Solo se afirma para moviles colombianos (57 + 3xxxxxxxxx), que es lo que
    esta app recoge. Un numero de otro pais se deja como "no se sabe" antes
    que arriesgar un enlace de WhatsApp que no existe.
    """
    digitos = solo_digitos(telefono)
    return len(digitos) == 12 and digitos.startswith("573")


def _enriquecer(fila: dict) -> dict:
    """Anade a la fila lo que la pagina necesita y la base no guarda.

    El telefono se normaliza aqui, no solo al guardarlo: las campanas
    anteriores a la normalizacion dejaron en la base numeros como
    "312 7217006", y un enlace de WhatsApp con un espacio dentro no abre.
    """
    telefono = solo_digitos(fila.get("telefono") or "")
    fila["telefono"] = telefono
    fila["tiene_telefono"] = bool(telefono)
    fila["es_celular"] = es_celular(telefono)
    fila["whatsapp_url"] = f"https://wa.me/{telefono}" if es_celular(telefono) else ""
    fila["telefono_url"] = f"tel:+{telefono}" if telefono else ""
    fila["estado_etiqueta"] = ETIQUETA_ESTADO.get(fila.get("estado"), fila.get("estado", ""))
    proximo = fila.get("proximo_paso") or ""
    fila["vencido"] = bool(proximo) and proximo <= date.today().isoformat()
    return fila


# --------------------------------------------------------------- lectura
def opciones() -> dict:
    """Todo lo que la pagina necesita para pintarse: vocabulario y filtros."""
    hoy = date.today().isoformat()
    resumen = storage.crm_resumen()
    return {
        "estados": ESTADOS,
        "canales": CANALES,
        "ordenes": ORDENES,
        "grupos": ESTADOS_POR_GRUPO,
        **storage.crm_valores_distintos(),
        "resumen": {e["clave"]: resumen.get(e["clave"], 0) for e in ESTADOS},
        "total": sum(resumen.values()),
        "agenda_hoy": storage.crm_agenda(hoy),
        "hoy": hoy,
    }


def listar(filtros: dict, limite: int, pagina: int, orden: str) -> dict:
    limite = max(1, min(limite, MAX_POR_PAGINA))
    pagina = max(1, pagina)
    filas, total = storage.crm_listar(
        filtros, limite=limite, desplazamiento=(pagina - 1) * limite, orden=orden
    )
    return {
        "clientes": [_enriquecer(f) for f in filas],
        "total": total,
        "pagina": pagina,
        "limite": limite,
        "paginas": max(1, -(-total // limite)),
    }


def detalle(place_id: str) -> dict | None:
    fila = storage.crm_cliente(place_id)
    if fila is None:
        return None
    return {
        "cliente": _enriquecer(fila),
        "interacciones": storage.crm_interacciones(place_id),
    }


# -------------------------------------------------------------- escritura
def registrar(
    place_id: str, estado: str, canal: str, comentario: str,
    proximo_paso: str, responsable: str,
) -> dict:
    """
    Guarda una interaccion y devuelve el cliente ya actualizado.

    Es el UNICO camino de escritura del CRM. Cambiar el estado desde la lista
    y anotar una llamada larga pasan los dos por aqui, asi que no hay forma de
    que un estado cambie sin quedar registrado quien, cuando y por que.
    """
    if estado not in CLAVES_ESTADO:
        raise ErrorCRM(f"Estado desconocido: {estado!r}")
    if canal not in CLAVES_CANAL:
        raise ErrorCRM(f"Canal desconocido: {canal!r}")
    if storage.crm_cliente(place_id) is None:
        raise ErrorCRM("Ese negocio no esta en la base de datos.")

    comentario = (comentario or "").strip()
    storage.crm_guardar_interaccion(
        interaccion_id=uuid.uuid4().hex[:16],
        place_id=place_id,
        fecha=ahora_iso(),
        canal=canal,
        estado=estado,
        comentario=comentario,
        proximo_paso=(proximo_paso or "").strip(),
        responsable=(responsable or "").strip(),
        cuenta_intento=canal != CANAL_SIN_INTENTO,
    )

    datos = detalle(place_id)
    datos["aviso"] = _reflejar_en_sheet(
        place_id, estado, comentario or datos["cliente"]["comentario"]
    )
    return datos


def _reflejar_en_sheet(place_id: str, estado: str, comentario: str) -> str:
    """Copia al Sheet lo ultimo anotado. Nunca puede tumbar el guardado.

    Va despues de escribir en la base a proposito: el dato ya esta a salvo,
    asi que un Sheet caido solo cuesta que la fila del Sheet se vea vieja
    hasta el proximo volcado.
    """
    from app import sheets
    from app.config import settings

    if not settings.crm_sync_sheet:
        return ""
    return sheets.escribir_seguimiento_de_uno(
        place_id, ETIQUETA_ESTADO.get(estado, estado), comentario
    )


# ------------------------------------------- puente con el Google Sheet
# Hasta ahora el seguimiento se llevaba a mano en el Sheet: la columna N
# ("Estado de contacto") y la P ("Comentario"). Esto recupera ese trabajo en
# lugar de pedirle al usuario que lo vuelva a escribir.

# Frase escrita a mano -> estado de la app. Se compara sin tildes y en
# minusculas, y basta con que la frase aparezca dentro del texto.
_TEXTO_A_ESTADO = [
    # EL ORDEN IMPORTA: gana la primera frase que aparezca en el texto. Las
    # negaciones van primero porque "no le interesa" tambien contiene
    # "interesa", y al reves quedaria marcado como interesado.
    ("no contest", "no_contesta"),
    ("no responde", "no_contesta"),
    ("no atiende", "no_contesta"),
    ("buzon", "no_contesta"),
    ("no le interesa", "no_interesa"),
    ("no interesa", "no_interesa"),
    ("no esta interesad", "no_interesa"),
    ("no estan interesad", "no_interesa"),
    ("sin interes", "no_interesa"),
    ("no quiere", "no_interesa"),
    ("descartad", "no_interesa"),
    ("numero equivocado", "numero_malo"),
    ("numero malo", "numero_malo"),
    ("numero errado", "numero_malo"),
    ("no existe", "numero_malo"),
    ("volver a llamar", "volver_a_llamar"),
    ("llamar despues", "volver_a_llamar"),
    ("llamar mas tarde", "volver_a_llamar"),
    ("pendiente", "volver_a_llamar"),
    ("pidio info", "pidio_info"),
    ("enviar info", "pidio_info"),
    ("mandar info", "pidio_info"),
    ("whatsapp", "pidio_info"),
    ("info enviada", "info_enviada"),
    ("correo enviado", "info_enviada"),
    ("enviad", "info_enviada"),
    ("interesad", "interesado"),
    ("cliente", "cliente"),
    ("cerrad", "cliente"),
    ("vendid", "cliente"),
    ("finalizad", "finalizado"),
    ("terminad", "finalizado"),
    ("contactad", "contactado"),
    ("llamad", "contactado"),
]


def _sin_tildes(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto or "")
    return plano.encode("ascii", "ignore").decode("ascii").strip().lower()


def interpretar_estado(texto: str) -> str:
    """
    Adivina el estado a partir de lo que hay escrito en la columna N.

    Si no reconoce la frase pero hay algo escrito, devuelve "contactado":
    equivocarse hacia "ya le hablamos" es mas seguro que hacia "sin contactar",
    porque lo segundo haria volver a llamar a alguien con quien ya se hablo.
    El texto original nunca se pierde: va al comentario.
    """
    plano = _sin_tildes(texto)
    if not plano:
        return ""
    for frase, estado in _TEXTO_A_ESTADO:
        if frase in plano:
            return estado
    return "contactado"


def importar_desde_sheet() -> dict:
    """
    Trae al CRM el estado y los comentarios escritos a mano en el Sheet.

    No pisa nada: los clientes que ya tienen seguimiento en la app se saltan,
    porque el dato de la app es el mas reciente. Se puede repetir sin miedo.
    """
    from app import sheets

    filas_sheet, aviso = sheets.leer_seguimiento_manual()
    if aviso:
        return {"importados": 0, "leidos": 0, "aviso": aviso}

    conocidos = storage.crm_place_ids_conocidos()
    ahora = ahora_iso()
    candidatas = []
    for fila in filas_sheet:
        if fila["place_id"] not in conocidos:
            continue
        estado = interpretar_estado(fila["estado"])
        comentario = fila["comentario"]
        if not estado and not comentario:
            continue
        # El texto original de la columna N se conserva junto al comentario:
        # la traduccion a un estado es una suposicion, el texto no.
        partes = [p for p in (fila["estado"], comentario) if p]
        candidatas.append((
            fila["place_id"],
            estado or "contactado",
            "",                       # responsable
            "",                       # proximo paso
            "",                       # ultimo contacto: no lo sabemos
            "",                       # ultimo canal
            0,                        # intentos
            " | ".join(partes),
            ahora,
        ))

    importados = storage.crm_sembrar(candidatas)
    return {
        "importados": importados,
        "leidos": len(filas_sheet),
        "aviso": (
            f"{importados} clientes tomaron su estado del Sheet. Los que ya "
            "tenian seguimiento en esta pagina se dejaron como estaban."
        ),
    }


def sincronizar_sheet() -> dict:
    """
    Vuelca al Sheet el seguimiento entero: estado en N, comentario en Q.

    Existe para ponerse al dia de golpe, por ejemplo si estuviste anotando con
    CRM_SYNC_SHEET apagado o si el Sheet estuvo caido un rato.
    """
    from app import sheets

    datos = {
        place_id: (ETIQUETA_ESTADO.get(fila["estado"], fila["estado"]),
                   fila["comentario"])
        for place_id, fila in storage.crm_seguimiento_completo().items()
        if fila["estado"] != storage.ESTADO_INICIAL
    }
    escritas, aviso = sheets.escribir_seguimiento(datos)
    return {
        "celdas_actualizadas": escritas,
        "aviso": aviso or (
            f"{escritas} celdas actualizadas en el Sheet "
            "(estado en la N, comentario en la Q)."
        ),
    }
