"""
Generador de Leads desde Google Maps - Backend FastAPI.

Arrancar:  python run.py      (o)   uvicorn app.main:app --reload
Abrir:     http://127.0.0.1:8000
"""
import hashlib
import hmac
import secrets
import unicodedata
import uuid
from datetime import date

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import campaign, crm, exports, places, sheets, storage, turso
from app.classifier import clasificar
from app.config import RAIZ, settings
from app.models import (
    InteraccionEntrada,
    Negocio,
    ParametrosBusqueda,
    ProgresoCampana,
    ResultadoBusqueda,
    ResultadoCampana,
)
from app.social_domains import CANDIDATOS_OPCIONALES, LISTA_REDES_SOCIALES

app = FastAPI(title="Generador de Leads desde Google Maps", version="1.0.0")

DIR_STATIC = RAIZ / "static"


@app.exception_handler(turso.ErrorTurso)
def _fallo_base_de_datos(request, exc: turso.ErrorTurso) -> JSONResponse:
    """
    La base remota no responde. Sin ella no hay dedupe ni contador de cuota,
    asi que es mejor parar y decirlo claro que seguir gastando a ciegas.
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                f"No se pudo usar la base de datos: {exc} "
                "Nada se ha gastado. Revisa que TURSO_DATABASE_URL y "
                "TURSO_AUTH_TOKEN esten bien puestos en las variables de "
                "entorno y que la base siga activa en turso.tech."
            )
        },
    )

# Cache en memoria de la ultima busqueda, para el boton de descarga.
_ultima_busqueda: dict = {"id": None, "negocios": [], "params": None}


# ------------------------------------------------------------------ estado
@app.get("/api/estado")
def estado() -> dict:
    """Configuracion y consumo actual, para pintar los avisos del frontend."""
    usados = storage.requests_hoy()
    return {
        "demo_mode": settings.demo_mode,
        "api_key_configurada": bool(settings.google_maps_api_key),
        "sheets_habilitado": settings.sheets_habilitado,
        "sheet_url": settings.sheet_url,
        "requests_hoy": usados,
        "max_requests_dia": settings.max_requests_per_day,
        "requests_restantes": max(0, settings.max_requests_per_day - usados),
        "max_paginas": settings.max_pages_per_search,
        "dia": date.today().isoformat(),
        "redes_sociales_activas": sorted(LISTA_REDES_SOCIALES),
        "redes_sociales_disponibles": sorted(CANDIDATOS_OPCIONALES),
        "confirmar_antes_de_gastar": settings.confirmar_antes_de_gastar,
        "precio_1000_con_rating": places.PRECIO_BUSQUEDA_RATING,
        "precio_1000_sin_rating": places.PRECIO_BUSQUEDA_BASE,
        "precio_1000_geocoding": places.PRECIO_GEOCODING,
        "ciudades_ya_geocodificadas": storage.ciudades_en_cache(),
    }


# --------------------------------------------------------------- busqueda
@app.post("/api/buscar", response_model=ResultadoBusqueda)
def buscar(
    params: ParametrosBusqueda,
    incluir_rating: bool = Query(True, description="Pedir rating/resenas (cuesta un poco mas)"),
    guardar: bool = Query(True, description="Guardar en historico y en Google Sheets"),
) -> ResultadoBusqueda:
    try:
        encontrados, requests_usados, avisos = places.buscar_negocios(
            params, incluir_rating=incluir_rating
        )
    except places.CuotaDiariaExcedida as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except places.ErrorPlaces as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    negocios = [clasificar(negocio) for negocio in encontrados]
    negocios.sort(key=lambda n: (not n.es_lead, -(n.resenas or 0)))

    busqueda_id = uuid.uuid4().hex[:12]
    leads = sum(1 for n in negocios if n.es_lead)

    nuevos_sheet = duplicados_sheet = 0
    if guardar and negocios:
        nuevos_local, duplicados_local = storage.guardar_negocios(negocios, busqueda_id)
        storage.registrar_busqueda(
            busqueda_id,
            negocios[0].fecha_busqueda,
            params.ciudad,
            params.categoria,
            params.radio_km,
            len(negocios),
            leads,
        )
        avisos.append(
            f"Historico local: {nuevos_local} negocios nuevos, "
            f"{duplicados_local} ya estaban registrados."
        )
        nuevos_sheet, duplicados_sheet, aviso_sheet = sheets.agregar_negocios(negocios)
        if aviso_sheet:
            avisos.append(aviso_sheet)
        elif settings.sheets_habilitado:
            avisos.append(
                f"Google Sheets: {nuevos_sheet} filas agregadas, "
                f"{duplicados_sheet} duplicados omitidos."
            )

    _ultima_busqueda.update(
        {"id": busqueda_id, "negocios": negocios, "params": params}
    )

    usados_hoy = storage.requests_hoy()
    return ResultadoBusqueda(
        busqueda_id=busqueda_id,
        parametros=params,
        total_encontrados=len(negocios),
        total_leads=leads,
        total_ya_tienen_web=len(negocios) - leads,
        nuevos_en_sheet=nuevos_sheet,
        duplicados_omitidos=duplicados_sheet,
        requests_usados=requests_usados,
        costo_estimado_usd=places.costo_estimado(requests_usados, incluir_rating),
        requests_restantes_hoy=max(0, settings.max_requests_per_day - usados_hoy),
        sheet_url=settings.sheet_url,
        demo=settings.demo_mode,
        avisos=avisos,
        negocios=negocios,
    )


# --------------------------------------------------------------- campanas
@app.post("/api/campana/buscar", response_model=ResultadoCampana)
def campana_buscar(
    params: ParametrosBusqueda,
    incluir_rating: bool = Query(True),
    max_celdas: int | None = Query(None, ge=1, le=50),
    guardar: bool = Query(True),
) -> ResultadoCampana:
    """
    Explora el siguiente lote de sectores sin explorar y devuelve SOLO
    negocios nuevos. Repetir la llamada avanza por el mapa, no repite.
    """
    try:
        resultado = campaign.ejecutar_sesion(
            params, incluir_rating=incluir_rating,
            max_celdas=max_celdas, guardar=guardar,
        )
    except places.CuotaDiariaExcedida as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except places.ErrorPlaces as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    negocios = resultado["negocios"]
    if negocios:
        _ultima_busqueda.update(
            {"id": resultado["busqueda_id"], "negocios": negocios, "params": params}
        )

    avisos = list(resultado["avisos"])
    if guardar and negocios:
        nuevos_sheet, dup_sheet, aviso_sheet = sheets.agregar_negocios(negocios)
        if aviso_sheet:
            avisos.append(aviso_sheet)
        elif settings.sheets_habilitado:
            avisos.append(
                f"Google Sheets: {nuevos_sheet} filas agregadas, "
                f"{dup_sheet} duplicados omitidos."
            )

    usados_hoy = storage.requests_hoy()
    return ResultadoCampana(
        campana_id=resultado["campana_id"],
        busqueda_id=resultado["busqueda_id"],
        parametros=params,
        total_nuevos=len(negocios),
        total_leads=sum(1 for n in negocios if n.es_lead),
        ya_conocidos_descartados=resultado["ya_conocidos_descartados"],
        sectores_explorados=resultado["sectores_explorados"],
        progreso=ProgresoCampana(**resultado["progreso"]),
        terminada=resultado["terminada"],
        requests_usados=resultado["requests_usados"],
        costo_estimado_usd=places.costo_estimado(
            resultado["requests_usados"], incluir_rating
        ),
        requests_restantes_hoy=max(0, settings.max_requests_per_day - usados_hoy),
        sheet_url=settings.sheet_url,
        demo=settings.demo_mode,
        avisos=avisos,
        negocios=negocios,
    )


@app.get("/api/campana/estado")
def campana_estado(ciudad: str, categoria: str, modo: str = "keyword") -> dict:
    """Progreso de una campana sin gastar nada. Sirve para pintar la barra."""
    campana_id = storage.id_campana(ciudad, categoria, modo)
    campana = storage.obtener_campana(campana_id)
    if campana is None:
        return {"existe": False, "campana_id": campana_id}
    return {"existe": True, "campana_id": campana_id, **campana,
            **storage.progreso_campana(campana_id)}


@app.get("/api/campanas")
def campanas_listar() -> dict:
    return {"campanas": storage.listar_campanas()}


@app.post("/api/campana/reiniciar")
def campana_reiniciar(ciudad: str, categoria: str, modo: str = "keyword") -> dict:
    """
    Marca todos los sectores como pendientes otra vez.

    Util meses despues para recapturar negocios que abrieron desde entonces.
    Los Place ID ya guardados se siguen filtrando: no se duplica nada.
    """
    campana_id = storage.id_campana(ciudad, categoria, modo)
    if storage.obtener_campana(campana_id) is None:
        raise HTTPException(status_code=404, detail="Esa campana no existe todavia.")
    reiniciadas = storage.reiniciar_campana(campana_id)
    return {
        "campana_id": campana_id,
        "sectores_reiniciados": reiniciadas,
        "mensaje": f"{reiniciadas} sectores vuelven a estar pendientes. "
                   "Los negocios ya guardados se seguiran filtrando.",
    }


# --------------------------------------------------------------- historico
@app.get("/api/historico")
def ver_historico(limite: int = 500, solo_leads: bool = False) -> dict:
    return {
        "negocios": storage.historico(limite=limite, solo_leads=solo_leads),
        "busquedas": storage.listar_busquedas(),
    }


# --------------------------------------------------------------- descargas
def _fila_a_negocio(fila: dict) -> Negocio:
    """Fila de SQLite -> modelo Negocio (ignora columnas tecnicas extra)."""
    datos = {
        campo: fila[campo]
        for campo in Negocio.model_fields
        if campo in fila and fila[campo] is not None
    }
    datos["es_lead"] = bool(fila.get("es_lead"))
    return Negocio(**datos)


def _negocios_para_descarga(busqueda_id: str | None) -> tuple[list[Negocio], str]:
    if busqueda_id in (None, "", "ultima"):
        if not _ultima_busqueda["negocios"]:
            raise HTTPException(
                status_code=404,
                detail="Todavia no hay una busqueda en esta sesion. Haz una busqueda "
                "primero, o descarga el historico completo.",
            )
        params = _ultima_busqueda["params"]
        etiqueta = f"{params.ciudad}_{params.categoria}".replace(" ", "_")
        return _ultima_busqueda["negocios"], etiqueta

    if busqueda_id == "historico":
        filas = storage.historico(limite=100000)
    else:
        filas = storage.negocios_de_busqueda(busqueda_id)
    if not filas:
        raise HTTPException(status_code=404, detail="No hay datos para esa busqueda.")

    return [_fila_a_negocio(fila) for fila in filas], busqueda_id


def _limpiar(texto: str) -> str:
    """Nombre de archivo seguro y ASCII (las cabeceras HTTP no aceptan tildes)."""
    sin_tildes = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    limpio = "".join(c if c.isalnum() else "_" for c in sin_tildes)
    limpio = "_".join(p for p in limpio.split("_") if p)
    return limpio[:60] or "leads"


def _construir_archivo(
    formato: str, negocios: list[Negocio], etiqueta: str, solo_leads: bool
) -> Response:
    if formato not in ("xlsx", "csv"):
        raise HTTPException(status_code=400, detail="Formato debe ser 'xlsx' o 'csv'.")

    if solo_leads:
        negocios = [n for n in negocios if n.es_lead]
    if not negocios:
        raise HTTPException(status_code=404, detail="No hay filas que descargar.")

    nombre = f"leads_{_limpiar(etiqueta)}.{formato}"
    if formato == "csv":
        contenido = exports.a_csv(negocios)
        media = "text/csv; charset=utf-8"
    else:
        contenido = exports.a_xlsx(negocios)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return Response(
        content=contenido,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.post("/api/descargar/{formato}")
def descargar_resultado(
    formato: str,
    negocios: list[Negocio],
    etiqueta: str = "leads",
    solo_leads: bool = False,
) -> Response:
    """
    Genera el archivo a partir de las filas que manda el navegador.

    Existe porque desplegado en serverless no hay una "ultima busqueda" en
    memoria que compartan las peticiones: cada una puede caer en una instancia
    distinta. El frontend ya tiene los resultados en pantalla, asi que los
    reenvia y esto solo da formato. Funciona igual aunque la busqueda se
    hiciera con "guardar" desactivado.
    """
    return _construir_archivo(formato, negocios, etiqueta, solo_leads)


@app.get("/api/descargar/{formato}")
def descargar(
    formato: str,
    busqueda_id: str | None = None,
    solo_leads: bool = False,
) -> Response:
    """Descarga desde la base de datos: una busqueda guardada o el historico."""
    negocios, etiqueta = _negocios_para_descarga(busqueda_id)
    return _construir_archivo(formato, negocios, etiqueta, solo_leads)


# ----------------------------------------------------------------- frontend
@app.get("/")
def index() -> FileResponse:
    return FileResponse(DIR_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=DIR_STATIC), name="static")


# =====================================================================
# Seguimiento de clientes (/crm)
# =====================================================================
# Vive en el mismo dominio y la misma app que el buscador porque trabaja
# sobre la misma base: los negocios que encuentra el buscador son los
# clientes a los que hay que llamar.

COOKIE_CRM = "crm_sesion"
_DIAS_SESION_CRM = 30


def _token_crm() -> str:
    """Cookie derivada de la clave. No se guarda ninguna sesion en memoria.

    Hace falta que sea asi porque en serverless cada peticion puede caer en
    una instancia distinta: una tabla de sesiones en RAM caducaria sola y de
    forma impredecible.
    """
    return hmac.new(
        settings.crm_password.encode("utf-8"), b"crm-seguimiento", hashlib.sha256
    ).hexdigest()


def exigir_crm(request: Request) -> None:
    """Puerta del seguimiento. Sin CRM_PASSWORD configurada, no hay puerta."""
    if not settings.crm_protegido:
        return
    if not secrets.compare_digest(request.cookies.get(COOKIE_CRM, ""), _token_crm()):
        raise HTTPException(
            status_code=401,
            detail="Necesitas la clave para ver el seguimiento de clientes.",
        )


@app.get("/api/crm/sesion")
def crm_sesion(request: Request) -> dict:
    """Si la pagina necesita clave y si este navegador ya la dio."""
    if not settings.crm_protegido:
        return {"protegido": False, "autenticado": True}
    valida = secrets.compare_digest(
        request.cookies.get(COOKIE_CRM, ""), _token_crm()
    )
    return {"protegido": True, "autenticado": valida}


@app.post("/api/crm/login")
def crm_login(
    request: Request, respuesta: Response, clave: str = Body("", embed=True)
) -> dict:
    if not settings.crm_protegido:
        return {"protegido": False, "autenticado": True}
    if not secrets.compare_digest(clave.strip(), settings.crm_password):
        raise HTTPException(status_code=401, detail="Clave incorrecta.")
    respuesta.set_cookie(
        COOKIE_CRM,
        _token_crm(),
        max_age=_DIAS_SESION_CRM * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"protegido": True, "autenticado": True}


@app.post("/api/crm/logout")
def crm_logout(respuesta: Response) -> dict:
    respuesta.delete_cookie(COOKIE_CRM)
    return {"protegido": settings.crm_protegido, "autenticado": False}


crm_router = APIRouter(prefix="/api/crm", dependencies=[Depends(exigir_crm)])


@crm_router.get("/opciones")
def crm_opciones() -> dict:
    """Vocabulario y valores de los filtros. Una sola llamada al abrir."""
    return crm.opciones()


def _filtros_crm(
    texto: str, categoria: str, ciudad: str, responsable: str,
    estados: list[str], contactado: str, es_lead: str, telefono: str,
    agenda: bool,
) -> dict:
    return {
        "texto": texto,
        "categoria": categoria,
        "ciudad": ciudad,
        "responsable": responsable,
        "estados": [e for e in estados if e in crm.CLAVES_ESTADO],
        "contactado": contactado,
        "es_lead": es_lead,
        "telefono": telefono,
        "agenda_hasta": date.today().isoformat() if agenda else "",
    }


@crm_router.get("/clientes")
def crm_clientes(
    texto: str = "",
    categoria: str = "",
    ciudad: str = "",
    responsable: str = "",
    estados: list[str] = Query(default=[]),
    contactado: str = Query("", pattern="^(si|no|)$"),
    es_lead: str = Query("", pattern="^(si|no|)$"),
    telefono: str = Query("", pattern="^(con|sin|celular|fijo|)$"),
    agenda: bool = False,
    orden: str = "relevancia",
    pagina: int = Query(1, ge=1),
    limite: int = Query(60, ge=1, le=crm.MAX_POR_PAGINA),
) -> dict:
    filtros = _filtros_crm(
        texto, categoria, ciudad, responsable, estados,
        contactado, es_lead, telefono, agenda,
    )
    return crm.listar(filtros, limite=limite, pagina=pagina, orden=orden)


@crm_router.get("/cliente/{place_id}")
def crm_cliente(place_id: str) -> dict:
    datos = crm.detalle(place_id)
    if datos is None:
        raise HTTPException(status_code=404, detail="Ese negocio no existe.")
    return datos


@crm_router.post("/cliente/{place_id}/interaccion")
def crm_interaccion(place_id: str, entrada: InteraccionEntrada) -> dict:
    """Anota una llamada, un WhatsApp, un correo o una nota, y fija el estado."""
    try:
        return crm.registrar(
            place_id=place_id,
            estado=entrada.estado,
            canal=entrada.canal,
            comentario=entrada.comentario,
            proximo_paso=entrada.proximo_paso,
            responsable=entrada.responsable,
        )
    except crm.ErrorCRM as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@crm_router.get("/descargar/{formato}")
def crm_descargar(
    formato: str,
    texto: str = "",
    categoria: str = "",
    ciudad: str = "",
    responsable: str = "",
    estados: list[str] = Query(default=[]),
    contactado: str = Query("", pattern="^(si|no|)$"),
    es_lead: str = Query("", pattern="^(si|no|)$"),
    telefono: str = Query("", pattern="^(con|sin|celular|fijo|)$"),
    agenda: bool = False,
    orden: str = "relevancia",
) -> Response:
    """Baja a Excel o CSV exactamente lo que se ve con los filtros puestos."""
    if formato not in ("xlsx", "csv"):
        raise HTTPException(status_code=400, detail="Formato debe ser 'xlsx' o 'csv'.")

    filtros = _filtros_crm(
        texto, categoria, ciudad, responsable, estados,
        contactado, es_lead, telefono, agenda,
    )
    # Una sola pagina grande: el tope existe para no armar un Excel de 50 MB
    # sin querer, no para limitar el trabajo del dia.
    datos = crm.listar(filtros, limite=crm.MAX_POR_PAGINA, pagina=1, orden=orden)
    clientes = datos["clientes"]
    if not clientes:
        raise HTTPException(status_code=404, detail="No hay filas que descargar.")

    if formato == "csv":
        contenido = exports.crm_a_csv(clientes)
        media = "text/csv; charset=utf-8"
    else:
        contenido = exports.crm_a_xlsx(clientes)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    nombre = f"seguimiento_{_limpiar(categoria or ciudad or 'clientes')}.{formato}"
    return Response(
        content=contenido,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@crm_router.post("/sheet/importar")
def crm_importar_sheet() -> dict:
    """
    Recupera el estado y los comentarios que ya estaban escritos a mano.

    Se puede repetir sin miedo: nunca pisa un seguimiento hecho desde aqui.
    """
    return crm.importar_desde_sheet()


@crm_router.post("/sheet/sincronizar")
def crm_sincronizar_sheet() -> dict:
    """Vuelca el estado actual a la columna N del Sheet. Nunca toca la P."""
    return crm.sincronizar_sheet()


app.include_router(crm_router)


@app.get("/crm")
def pagina_crm() -> FileResponse:
    return FileResponse(DIR_STATIC / "crm.html")
