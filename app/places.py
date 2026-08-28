"""
Cliente de Google Places API (New) + Geocoding API.

Puntos clave (secciones 2 y 6 del proyecto):
- SIEMPRE se usa Field Masking: solo se piden los campos de CAMPOS_*.
  Pedir campos de mas sube el SKU y por lo tanto el precio.
- Cada llamada HTTP se cuenta contra un tope diario local (MAX_REQUESTS_PER_DAY).
- Nunca se hace scraping del HTML de Google Maps.
"""
import hashlib

import httpx

from app import grid, storage
from app.config import settings
from app.models import Negocio, ParametrosBusqueda, ahora_iso

URL_TEXT_SEARCH = "https://places.googleapis.com/v1/places:searchText"
URL_NEARBY_SEARCH = "https://places.googleapis.com/v1/places:searchNearby"
URL_GEOCODING = "https://maps.googleapis.com/maps/api/geocode/json"

# --- Field Masking -------------------------------------------------------
# Campos base. Incluyen websiteUri y telefono, que suben el SKU a Enterprise,
# pero son imprescindibles: sin websiteUri no se puede clasificar el lead.
CAMPOS_BASE = [
    "id",
    "displayName",
    "formattedAddress",
    "nationalPhoneNumber",
    "internationalPhoneNumber",
    "websiteUri",
    "primaryType",
    "types",
    "googleMapsUri",
]
# Campos de "atmosfera": suben un escalon mas el precio. Opcionales.
CAMPOS_RATING = ["rating", "userRatingCount"]

# --- Precios ESTIMADOS (USD por 1000 requests) ---------------------------
# Solo para mostrar una referencia en pantalla. Los precios reales los fija
# Google y cambian: verificar en https://mapsplatform.google.com/pricing/
PRECIO_BUSQUEDA_BASE = 40.0    # Search - SKU Enterprise
PRECIO_BUSQUEDA_RATING = 45.0  # SKU Enterprise + Atmosphere
PRECIO_GEOCODING = 5.0

MAX_RESULTADOS_POR_PAGINA = 20


class ErrorPlaces(Exception):
    """Error controlado que el frontend puede mostrar tal cual."""


class CuotaDiariaExcedida(ErrorPlaces):
    pass


def _field_mask(prefijo: str, incluir_rating: bool) -> str:
    campos = CAMPOS_BASE + (CAMPOS_RATING if incluir_rating else [])
    return ",".join(f"{prefijo}{c}" for c in campos)


def _verificar_cuota(requests_a_gastar: int = 1) -> None:
    usados = storage.requests_hoy()
    if usados + requests_a_gastar > settings.max_requests_per_day:
        raise CuotaDiariaExcedida(
            f"Tope diario alcanzado ({usados}/{settings.max_requests_per_day} "
            "requests hoy). Se detuvo la busqueda para no generar mas costo. "
            "Puedes subir MAX_REQUESTS_PER_DAY en el archivo .env si lo necesitas."
        )


def _gastar_request() -> None:
    _verificar_cuota(1)
    storage.sumar_requests(1)


# ------------------------------------------------------------- geocoding
def geocodificar(ciudad: str) -> tuple[float, float, str]:
    """Ciudad -> (lat, lng, direccion_formateada). Cachea para no repetir costo."""
    cacheado = storage.geocache_leer(ciudad)
    if cacheado:
        return cacheado

    if settings.demo_mode:
        resultado = (4.7110, -74.0721, f"{ciudad} (demo)")
        storage.geocache_guardar(ciudad, *resultado)
        return resultado

    _gastar_request()
    try:
        respuesta = httpx.get(
            URL_GEOCODING,
            params={"address": ciudad, "key": settings.google_maps_api_key},
            timeout=20.0,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
    except httpx.HTTPError as exc:
        raise ErrorPlaces(f"No se pudo conectar con la Geocoding API: {exc}") from exc

    estado = datos.get("status")
    if estado == "ZERO_RESULTS":
        raise ErrorPlaces(
            f"No se encontro la ciudad '{ciudad}'. Prueba con mas detalle, "
            "por ejemplo 'Bogota, Colombia'."
        )
    if estado != "OK":
        raise ErrorPlaces(
            f"Geocoding API devolvio '{estado}': "
            f"{datos.get('error_message', 'sin detalle')}"
        )

    primero = datos["results"][0]
    loc = primero["geometry"]["location"]
    resultado = (loc["lat"], loc["lng"], primero.get("formatted_address", ciudad))
    storage.geocache_guardar(ciudad, *resultado)
    return resultado


# ---------------------------------------------------------------- parseo
def _a_negocio(place: dict, params: ParametrosBusqueda, fecha: str) -> Negocio:
    tipos = place.get("types") or []
    return Negocio(
        place_id=place.get("id", ""),
        nombre=(place.get("displayName") or {}).get("text", ""),
        direccion=place.get("formattedAddress", ""),
        telefono=place.get("nationalPhoneNumber")
        or place.get("internationalPhoneNumber")
        or "",
        sitio_web=place.get("websiteUri", "") or "",
        categoria_google=place.get("primaryType") or (tipos[0] if tipos else ""),
        rating=place.get("rating"),
        resenas=place.get("userRatingCount"),
        maps_url=place.get("googleMapsUri", ""),
        fecha_busqueda=fecha,
        ciudad_buscada=params.ciudad,
        categoria_buscada=params.categoria,
    )


def _llamar(url: str, cuerpo: dict, field_mask: str) -> dict:
    _gastar_request()
    try:
        respuesta = httpx.post(
            url,
            json=cuerpo,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.google_maps_api_key,
                "X-Goog-FieldMask": field_mask,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise ErrorPlaces(f"No se pudo conectar con Places API: {exc}") from exc

    if respuesta.status_code != 200:
        try:
            detalle = respuesta.json().get("error", {}).get("message", "")
        except Exception:
            detalle = respuesta.text[:300]
        if respuesta.status_code == 403:
            detalle += (
                " | Revisa que la Places API (New) este habilitada, que la API Key "
                "sea correcta y que sus restricciones permitan este servidor."
            )
        raise ErrorPlaces(f"Places API error {respuesta.status_code}: {detalle}")

    return respuesta.json()


# --------------------------------------------------------------- busqueda
def buscar_en_celda(
    lat: float,
    lng: float,
    lado_celda_km: float,
    params: ParametrosBusqueda,
    incluir_rating: bool = True,
    max_paginas: int = 3,
    fecha: str | None = None,
) -> dict[str, Negocio]:
    """
    Busca dentro de UNA celda concreta del mapa (centro ya conocido).

    Es la pieza que permite barrer una ciudad por zonas: cada llamada usa un
    recuadro distinto, y por eso devuelve negocios distintos aunque la palabra
    clave sea siempre la misma.

    Clave del diseno: se usa `locationRestriction` (frontera dura), no
    `locationBias` (preferencia blanda). Con Bias, al buscar en un barrio
    periferico Google devolveria igualmente los negocios del centro de la
    ciudad y el barrido no traeria nada nuevo.

    Devuelve {place_id: Negocio}.
    """
    fecha = fecha or ahora_iso()
    negocios: dict[str, Negocio] = {}

    if params.modo == "tipo":
        # Nearby Search solo admite circulos. Se toma el circulo circunscrito
        # para no dejar fuera las esquinas de la celda.
        radio_m = min(grid.radio_circunscrito_km(lado_celda_km) * 1000, 50000.0)
        datos = _llamar(
            URL_NEARBY_SEARCH,
            {
                "includedTypes": [params.categoria.strip().lower()],
                "maxResultCount": MAX_RESULTADOS_POR_PAGINA,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radio_m,
                    }
                },
                "languageCode": "es",
            },
            _field_mask("places.", incluir_rating),
        )
        for place in datos.get("places", []):
            negocio = _a_negocio(place, params, fecha)
            negocios[negocio.place_id] = negocio
        return negocios

    # Text Search: locationRestriction solo acepta RECTANGULO (viewport).
    rectangulo = grid.rectangulo_de(lat, lng, lado_celda_km)
    token: str | None = None
    for _ in range(max_paginas):
        cuerpo: dict = {
            "textQuery": params.categoria,
            "pageSize": MAX_RESULTADOS_POR_PAGINA,
            "languageCode": "es",
            "locationRestriction": {"rectangle": rectangulo},
        }
        if token:
            cuerpo["pageToken"] = token

        datos = _llamar(
            URL_TEXT_SEARCH,
            cuerpo,
            _field_mask("places.", incluir_rating) + ",nextPageToken",
        )

        for place in datos.get("places", []):
            negocio = _a_negocio(place, params, fecha)
            negocios[negocio.place_id] = negocio

        token = datos.get("nextPageToken")
        if not token:
            break

    return negocios


def buscar_negocios(
    params: ParametrosBusqueda, incluir_rating: bool = True
) -> tuple[list[Negocio], int, list[str]]:
    """Devuelve (negocios sin clasificar, requests_usados, avisos)."""
    if settings.demo_mode:
        return _buscar_demo(params)

    if not settings.google_maps_api_key:
        raise ErrorPlaces(
            "Falta GOOGLE_MAPS_API_KEY en el archivo .env. "
            "Mientras tanto puedes poner DEMO_MODE=true para probar la interfaz "
            "sin gastar dinero."
        )

    fecha = ahora_iso()
    avisos: list[str] = []
    antes = storage.requests_hoy()

    lat, lng, etiqueta = geocodificar(params.ciudad)
    avisos.append(f"Centro de busqueda: {etiqueta}")
    radio_m = min(params.radio_km * 1000, 50000.0)

    max_paginas = params.max_paginas or settings.max_pages_per_search
    max_paginas = max(1, min(max_paginas, settings.max_pages_per_search))

    negocios: dict[str, Negocio] = {}

    if params.modo == "tipo":
        # Nearby Search: categoria exacta de Places, sin paginacion (max 20).
        datos = _llamar(
            URL_NEARBY_SEARCH,
            {
                "includedTypes": [params.categoria.strip().lower()],
                "maxResultCount": MAX_RESULTADOS_POR_PAGINA,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radio_m,
                    }
                },
                "languageCode": "es",
            },
            _field_mask("places.", incluir_rating),
        )
        for place in datos.get("places", []):
            negocio = _a_negocio(place, params, fecha)
            negocios[negocio.place_id] = negocio
        avisos.append(
            "Modo 'tipo de negocio': la busqueda por categoria exacta devuelve "
            "maximo 20 resultados. Usa 'palabra clave' para obtener mas."
        )
    else:
        # Text Search: hasta 3 paginas de 20 = 60 resultados.
        token: str | None = None
        for pagina in range(max_paginas):
            cuerpo: dict = {
                "textQuery": f"{params.categoria} en {params.ciudad}",
                "pageSize": MAX_RESULTADOS_POR_PAGINA,
                "languageCode": "es",
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radio_m,
                    }
                },
            }
            if token:
                cuerpo["pageToken"] = token

            try:
                datos = _llamar(
                    URL_TEXT_SEARCH,
                    cuerpo,
                    _field_mask("places.", incluir_rating) + ",nextPageToken",
                )
            except CuotaDiariaExcedida as exc:
                avisos.append(f"Busqueda detenida: {exc}")
                break

            for place in datos.get("places", []):
                negocio = _a_negocio(place, params, fecha)
                negocios[negocio.place_id] = negocio

            token = datos.get("nextPageToken")
            if not token:
                break
            if pagina + 1 == max_paginas:
                avisos.append(
                    f"Hay mas resultados disponibles, pero se corto en "
                    f"{max_paginas} paginas por control de costos."
                )

    usados = storage.requests_hoy() - antes
    return list(negocios.values()), usados, avisos


# -------------------------------------------------------------- modo demo
_DEMO = [
    ("Peluqueria Estilo Norte", "Cra 15 #85-40", "+57 301 555 0101", "", 4.6, 128),
    ("Barberia El Corte", "Cl 72 #10-20", "+57 302 555 0102",
     "https://www.facebook.com/barberiaelcorte", 4.8, 340),
    ("Salon Bella Vista", "Av 68 #40-11", "+57 310 555 0103",
     "https://www.instagram.com/salonbellavista", 4.3, 76),
    ("Studio Hair Premium", "Cl 93 #12-05", "+57 315 555 0104",
     "https://studiohairpremium.com", 4.9, 512),
    ("Peluqueria Don Jose", "Cra 7 #22-18", "+57 320 555 0105", "", 4.1, 42),
    ("Beauty Center Chapinero", "Cl 60 #9-30", "+57 311 555 0106",
     "https://m.facebook.com/beautycenterchape", 4.5, 210),
    ("Corte & Color", "Cra 13 #45-60", "", "https://corteycolor.com.co", 4.7, 189),
    ("Glamour Salon", "Cl 100 #19-54", "+57 318 555 0108", "", 3.9, 25),
]


def _buscar_demo(params: ParametrosBusqueda) -> tuple[list[Negocio], int, list[str]]:
    fecha = ahora_iso()
    # Place ID determinista: repetir la misma busqueda debe detectar duplicados,
    # igual que pasaria con datos reales.
    semilla = f"{params.ciudad}|{params.categoria}".lower()
    sufijo = hashlib.sha1(semilla.encode("utf-8")).hexdigest()[:8]
    negocios = [
        Negocio(
            place_id=f"demo_{sufijo}_{i}",
            nombre=nombre,
            direccion=f"{direccion}, {params.ciudad}",
            telefono=telefono,
            sitio_web=web,
            categoria_google=params.categoria,
            rating=rating,
            resenas=resenas,
            maps_url="https://maps.google.com/?q=" + nombre.replace(" ", "+"),
            fecha_busqueda=fecha,
            ciudad_buscada=params.ciudad,
            categoria_buscada=params.categoria,
        )
        for i, (nombre, direccion, telefono, web, rating, resenas) in enumerate(_DEMO)
    ]
    return negocios, 0, ["MODO DEMO activo: datos de ejemplo, no se llamo a Google."]


def costo_estimado(requests_busqueda: int, incluir_rating: bool) -> float:
    precio = PRECIO_BUSQUEDA_RATING if incluir_rating else PRECIO_BUSQUEDA_BASE
    return round(requests_busqueda * precio / 1000, 4)
