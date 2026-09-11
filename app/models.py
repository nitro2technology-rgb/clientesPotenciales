"""Modelos de datos compartidos entre backend y frontend."""
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_NO_DIGITOS = re.compile(r"\D+")

# Colombia: movil = 10 digitos que empiezan por 3, fijo = 10 que empiezan por 6.
# Google los devuelve sin indicativo cuando entrega el numero en formato
# nacional, asi que se le antepone aqui. Cualquier otra longitud se deja tal
# cual: adivinar el pais de un numero suelto se equivoca mas de lo que acierta.
INDICATIVO_PAIS = "57"
_LARGO_NACIONAL = 10
_INICIOS_NACIONALES = ("3", "6")


def solo_digitos(telefono: str | None) -> str:
    """Normaliza un telefono a digitos pelados con indicativo de pais.

    '+57 312 721 7006' -> '573127217006'
    '(604) 322 1809'   -> '576043221809'

    Dos motivos. El '+' inicial hace que Google Sheets lea la celda como una
    formula y escriba #ERROR! en su lugar, y los espacios, parentesis y
    guiones estorban para buscar, marcar o cruzar los datos con otra tabla.
    """
    if not telefono:
        return ""
    digitos = _NO_DIGITOS.sub("", str(telefono))
    if len(digitos) == _LARGO_NACIONAL and digitos.startswith(_INICIOS_NACIONALES):
        return INDICATIVO_PAIS + digitos
    return digitos


class ParametrosBusqueda(BaseModel):
    ciudad: str = Field(..., min_length=2, description="Ej: 'Bogota, Colombia'")
    categoria: str = Field(..., min_length=2, description="Ej: 'peluquerias' o 'hair_salon'")
    radio_km: float = Field(5.0, gt=0, le=50, description="Radio en km (max 50)")
    modo: Literal["keyword", "tipo"] = "keyword"
    max_paginas: int | None = Field(None, ge=1, le=3)


class ProgresoCampana(BaseModel):
    total_celdas: int = 0
    celdas_exploradas: int = 0
    celdas_pendientes: int = 0
    negocios_nuevos_acumulados: int = 0
    porcentaje: float = 0.0
    terminada: bool = False


class ResultadoCampana(BaseModel):
    campana_id: str
    busqueda_id: str = ""
    parametros: ParametrosBusqueda
    total_nuevos: int = 0
    total_leads: int = 0
    ya_conocidos_descartados: int = 0
    sectores_explorados: int = 0
    progreso: ProgresoCampana
    terminada: bool = False
    requests_usados: int = 0
    costo_estimado_usd: float = 0.0
    requests_restantes_hoy: int = 0
    sheet_url: str = ""
    demo: bool = False
    avisos: list[str] = []
    negocios: list["Negocio"] = []


class Negocio(BaseModel):
    place_id: str
    nombre: str = ""
    direccion: str = ""
    telefono: str = ""
    sitio_web: str = ""
    categoria_google: str = ""
    rating: float | None = None
    resenas: int | None = None
    maps_url: str = ""
    email: str = ""            # reservado - Places API no expone emails
    estado_contacto: str = ""  # lo llena el usuario a mano

    # Clasificacion
    es_lead: bool = False
    motivo: str = ""

    # Contexto de la busqueda
    fecha_busqueda: str = ""
    ciudad_buscada: str = ""
    categoria_buscada: str = ""

    @field_validator("telefono", mode="before")
    @classmethod
    def _telefono_solo_digitos(cls, valor):
        return solo_digitos(valor)


class ResultadoBusqueda(BaseModel):
    busqueda_id: str
    parametros: ParametrosBusqueda
    total_encontrados: int
    total_leads: int
    total_ya_tienen_web: int
    nuevos_en_sheet: int = 0
    duplicados_omitidos: int = 0
    requests_usados: int = 0
    costo_estimado_usd: float = 0.0
    requests_restantes_hoy: int = 0
    sheet_url: str = ""
    demo: bool = False
    avisos: list[str] = []
    negocios: list[Negocio] = []


def ahora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class InteraccionEntrada(BaseModel):
    """Lo que manda la pagina de seguimiento al anotar una llamada o un cambio.

    `estado` es obligatorio a proposito: toda anotacion deja al cliente en un
    estado explicito, para que nunca haya que adivinar en que quedo la cosa.
    """
    estado: str = Field(..., min_length=2)
    canal: str = "llamada"
    comentario: str = ""
    proximo_paso: str = ""     # fecha ISO (YYYY-MM-DD), o vacio para quitarla
    responsable: str = ""

    @field_validator("proximo_paso", mode="before")
    @classmethod
    def _fecha_valida(cls, valor):
        """Acepta vacio o YYYY-MM-DD; cualquier otra cosa se descarta.

        Sin esto un texto libre entraria en la columna por la que se ordena la
        agenda y la dejaria mal ordenada sin que se note.
        """
        texto = (valor or "").strip()
        if not texto:
            return ""
        try:
            datetime.strptime(texto, "%Y-%m-%d")
        except ValueError:
            return ""
        return texto
