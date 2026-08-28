"""Modelos de datos compartidos entre backend y frontend."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


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
