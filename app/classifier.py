"""Seccion 3 del proyecto: decide si un negocio es lead valido."""
from app.models import Negocio
from app.social_domains import es_red_social

MOTIVO_SIN_WEB = "Sin sitio web"
MOTIVO_YA_TIENE = "Ya tiene sitio web propio"


def clasificar(negocio: Negocio) -> Negocio:
    website = (negocio.sitio_web or "").strip()

    if not website:
        negocio.es_lead = True
        negocio.motivo = MOTIVO_SIN_WEB
        return negocio

    dominio_social = es_red_social(website)
    if dominio_social:
        negocio.es_lead = True
        negocio.motivo = f"Sitio web es solo red social ({dominio_social})"
        return negocio

    negocio.es_lead = False
    negocio.motivo = MOTIVO_YA_TIENE
    return negocio
