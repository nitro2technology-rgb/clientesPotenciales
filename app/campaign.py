"""
Campanas de barrido: "traeme siempre negocios NUEVOS".

Como funciona
-------------
Una campana es la pareja (ciudad + categoria). La primera vez que buscas
"abogados en Bogota" se calcula una rejilla que cubre toda la zona y se guarda
como lista de celdas pendientes.

Cada vez que vuelves a lanzar esa misma busqueda, la app NO repite la consulta
anterior: coge las siguientes celdas sin explorar y busca ahi. Por eso manana
salen negocios distintos a los de hoy.

Ademas, todo lo que vuelve se filtra contra los Place ID ya guardados, asi que
en pantalla solo aparecen negocios que no tenias. Cuando ya no quedan celdas
pendientes, la campana se marca como terminada: no hay mas que sacar de Google
para esa ciudad y esa categoria.
"""
import uuid

from app import grid, places, storage
from app.classifier import clasificar
from app.config import settings
from app.models import Negocio, ParametrosBusqueda, ahora_iso


class ErrorCampana(Exception):
    pass


def _preparar(params: ParametrosBusqueda) -> tuple[str, dict, list[str]]:
    """Devuelve (campana_id, campana, avisos), creandola si es la primera vez."""
    avisos: list[str] = []
    campana_id = storage.id_campana(params.ciudad, params.categoria, params.modo)
    campana = storage.obtener_campana(campana_id)

    if campana is None:
        lat, lng, etiqueta = places.geocodificar(params.ciudad)
        lado = grid.lado_celda_recomendado(params.radio_km)
        celdas = grid.generar_celdas(lat, lng, params.radio_km, lado)
        storage.crear_campana(
            campana_id, params.ciudad, params.categoria, params.modo,
            params.radio_km, lado, lat, lng, celdas, ahora_iso(),
        )
        campana = storage.obtener_campana(campana_id)
        avisos.append(
            f"Campana nueva sobre {etiqueta}: la zona se dividio en "
            f"{len(celdas)} sectores de {lado:.0f} km de lado."
        )
    else:
        avisos.append(
            f"Continuando la campana '{params.categoria} en {params.ciudad}' "
            f"desde donde quedo."
        )

    return campana_id, campana, avisos


def ejecutar_sesion(
    params: ParametrosBusqueda,
    incluir_rating: bool = True,
    max_celdas: int | None = None,
    guardar: bool = True,
) -> dict:
    """
    Explora el siguiente lote de sectores pendientes y devuelve SOLO los
    negocios que no estaban ya en la base de datos.
    """
    if settings.demo_mode:
        return _sesion_demo(params, max_celdas)

    campana_id, campana, avisos = _preparar(params)
    lado = campana["radio_celda_km"]

    limite = max_celdas or settings.celdas_por_sesion
    limite = max(1, min(limite, settings.celdas_por_sesion))
    pendientes = storage.celdas_pendientes(campana_id, limite)

    if not pendientes:
        progreso = storage.progreso_campana(campana_id)
        return {
            "campana_id": campana_id,
            "negocios": [],
            "avisos": [
                "Esta campana ya esta COMPLETA: se exploraron los "
                f"{progreso['total_celdas']} sectores de la zona y no queda "
                "ninguno pendiente. Google no tiene mas negocios que dar para "
                "esta combinacion de ciudad y categoria.",
                "Para seguir: prueba otra palabra clave (por ejemplo "
                "'bufete' o 'asesoria juridica' en vez de 'abogados'), "
                "amplia el radio, o reinicia la campana si han pasado meses.",
            ],
            "progreso": progreso,
            "requests_usados": 0,
            "sectores_explorados": 0,
            "ya_conocidos_descartados": 0,
            "terminada": True,
        }

    fecha = ahora_iso()
    antes = storage.requests_hoy()
    conocidos = storage.place_ids_existentes()

    nuevos: dict[str, Negocio] = {}
    descartados = 0
    explorados = 0
    corte_por_cuota = False

    for celda in pendientes:
        try:
            encontrados = places.buscar_en_celda(
                celda["lat"], celda["lng"], lado, params,
                incluir_rating=incluir_rating,
                max_paginas=settings.max_pages_per_search,
                fecha=fecha,
            )
        except places.CuotaDiariaExcedida as exc:
            # Se acabo la cuota del dia: se para SIN marcar esta celda, para
            # retomarla manana justo donde quedo.
            avisos.append(f"Barrido detenido: {exc}")
            corte_por_cuota = True
            break

        # Aqui esta el filtro de "solo informacion nueva".
        nuevos_celda = {
            pid: n for pid, n in encontrados.items()
            if pid not in conocidos and pid not in nuevos
        }
        descartados += len(encontrados) - len(nuevos_celda)
        nuevos.update(nuevos_celda)

        storage.marcar_celda(
            campana_id, celda["indice"], fecha,
            len(encontrados), len(nuevos_celda),
        )
        explorados += 1

    negocios = [clasificar(n) for n in nuevos.values()]
    negocios.sort(key=lambda n: (not n.es_lead, -(n.resenas or 0)))

    busqueda_id = uuid.uuid4().hex[:12]
    if guardar and negocios:
        storage.guardar_negocios(negocios, busqueda_id)
        storage.registrar_busqueda(
            busqueda_id, fecha, params.ciudad, params.categoria,
            params.radio_km, len(negocios),
            sum(1 for n in negocios if n.es_lead),
        )

    progreso = storage.progreso_campana(campana_id)

    if descartados:
        avisos.append(
            f"Se descartaron {descartados} negocios que ya tenias registrados "
            "de busquedas anteriores: no se duplican."
        )
    if progreso["terminada"]:
        avisos.append(
            "Campana COMPLETA: ya se recorrieron todos los sectores de la zona."
        )
    elif not corte_por_cuota:
        avisos.append(
            f"Quedan {progreso['celdas_pendientes']} sectores por explorar. "
            "Vuelve a pulsar Buscar para continuar por donde va."
        )

    return {
        "campana_id": campana_id,
        "busqueda_id": busqueda_id,
        "negocios": negocios,
        "avisos": avisos,
        "progreso": progreso,
        "requests_usados": storage.requests_hoy() - antes,
        "sectores_explorados": explorados,
        "ya_conocidos_descartados": descartados,
        "terminada": progreso["terminada"],
    }


# -------------------------------------------------------------- modo demo
def _sesion_demo(params: ParametrosBusqueda, max_celdas: int | None) -> dict:
    """
    Simula el barrido sin llamar a Google: cada sesion inventa negocios
    distintos, para poder probar que nunca se repiten.
    """
    campana_id = storage.id_campana(params.ciudad, params.categoria, params.modo)
    campana = storage.obtener_campana(campana_id)

    if campana is None:
        lado = grid.lado_celda_recomendado(params.radio_km)
        celdas = grid.generar_celdas(4.7110, -74.0721, params.radio_km, lado)
        storage.crear_campana(
            campana_id, params.ciudad, params.categoria, params.modo,
            params.radio_km, lado, 4.7110, -74.0721, celdas, ahora_iso(),
        )

    limite = max_celdas or settings.celdas_por_sesion
    pendientes = storage.celdas_pendientes(campana_id, limite)
    fecha = ahora_iso()
    conocidos = storage.place_ids_existentes()

    negocios: list[Negocio] = []
    descartados = 0
    for celda in pendientes:
        for i in range(6):
            pid = f"demo_{campana_id}_{celda['indice']}_{i}"
            if pid in conocidos:
                descartados += 1
                continue
            negocios.append(
                clasificar(Negocio(
                    place_id=pid,
                    nombre=f"{params.categoria.title()} Sector {celda['indice']}-{i}",
                    direccion=f"Zona {celda['indice']}, {params.ciudad}",
                    telefono=f"+57 300 555 {celda['indice']:02d}{i:02d}",
                    sitio_web=["", "https://www.facebook.com/negocio",
                               "https://sitiopropio.com"][i % 3],
                    categoria_google=params.categoria,
                    rating=round(3.5 + (i % 3) * 0.5, 1),
                    resenas=20 + i * 15,
                    maps_url="https://maps.google.com/",
                    fecha_busqueda=fecha,
                    ciudad_buscada=params.ciudad,
                    categoria_buscada=params.categoria,
                ))
            )
        storage.marcar_celda(campana_id, celda["indice"], fecha, 6, 6)

    busqueda_id = uuid.uuid4().hex[:12]
    if negocios:
        storage.guardar_negocios(negocios, busqueda_id)

    progreso = storage.progreso_campana(campana_id)
    avisos = ["MODO DEMO: datos de ejemplo, no se llamo a Google."]
    if descartados:
        avisos.append(
            f"Se descartaron {descartados} negocios que ya tenias registrados."
        )
    if progreso["terminada"]:
        avisos.append(
            "Campana COMPLETA: ya se recorrieron todos los sectores de la zona."
        )
    else:
        avisos.append(
            f"Quedan {progreso['celdas_pendientes']} sectores por explorar. "
            "Vuelve a pulsar Buscar para continuar por donde va."
        )

    return {
        "campana_id": campana_id,
        "busqueda_id": busqueda_id,
        "negocios": negocios,
        "avisos": avisos,
        "progreso": progreso,
        "requests_usados": 0,
        "sectores_explorados": len(pendientes),
        "ya_conocidos_descartados": descartados,
        "terminada": progreso["terminada"],
    }
