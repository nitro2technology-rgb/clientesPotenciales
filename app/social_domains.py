"""
LISTA_REDES_SOCIALES
====================
Unico lugar del codigo donde se define que dominios cuentan como
"no es una pagina web propia".

Si un negocio pone como "sitio web" alguno de estos dominios, se considera
LEAD VALIDO (porque no tiene web real, solo un perfil).

Para ampliar la lista: agrega el dominio (sin http, sin www) a la seccion
correspondiente. Los subdominios se detectan solos:
"m.facebook.com" y "es-la.facebook.com" hacen match con "facebook.com".
"""

# --- Activos: se consideran "no tiene web propia" ---
LISTA_REDES_SOCIALES: set[str] = {
    # Facebook
    "facebook.com",
    "fb.com",
    "fb.me",
    "fb.watch",
    # Instagram
    "instagram.com",
    "instagr.am",
}

# --- Preparados pero DESACTIVADOS ---
# Mueve cualquiera de estos a LISTA_REDES_SOCIALES (arriba) cuando quieras
# que tambien cuenten como lead. Estan aqui listos para copiar/pegar.
CANDIDATOS_OPCIONALES: set[str] = {
    # WhatsApp
    "wa.me",
    "whatsapp.com",
    "api.whatsapp.com",
    # Agregadores de links
    "linktr.ee",
    "linkr.bio",
    "beacons.ai",
    "bio.link",
    "campsite.bio",
    "taplink.cc",
    # Otras redes
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "linkedin.com",
    "pinterest.com",
    # Constructores gratuitos / paginas "de relleno"
    "wixsite.com",
    "blogspot.com",
    "wordpress.com",
    "negocio.site",
    "business.site",  # Google Business "sitios web" auto-generados
}


def normalizar_dominio(url: str) -> str:
    """
    'https://www.Facebook.com/mi-negocio?ref=1' -> 'facebook.com'
    Devuelve '' si la url es vacia o no parseable.
    """
    if not url:
        return ""
    limpio = url.strip().lower()
    for prefijo in ("http://", "https://", "//"):
        if limpio.startswith(prefijo):
            limpio = limpio[len(prefijo):]
            break
    # cortar path, query y fragmento
    for separador in ("/", "?", "#"):
        limpio = limpio.split(separador, 1)[0]
    # cortar credenciales y puerto
    limpio = limpio.rsplit("@", 1)[-1].split(":", 1)[0]
    if limpio.startswith("www."):
        limpio = limpio[4:]
    return limpio.strip(".")


def es_red_social(url: str) -> str | None:
    """
    Devuelve el dominio de red social detectado, o None si es web propia.
    Hace match tambien con subdominios (m.facebook.com -> facebook.com).
    """
    dominio = normalizar_dominio(url)
    if not dominio:
        return None
    for social in LISTA_REDES_SOCIALES:
        if dominio == social or dominio.endswith("." + social):
            return social
    return None
