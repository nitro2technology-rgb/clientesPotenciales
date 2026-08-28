"""
Rejilla geografica para barrer una ciudad por partes.

El problema que resuelve
------------------------
La Places API devuelve como maximo 60 resultados por consulta, y si repites
la MISMA consulta manana te devuelve los MISMOS 60 (el ranking de relevancia
no cambia). No existe un "dame los siguientes 60".

La unica forma de seguir encontrando negocios nuevos es preguntarle a Google
por OTRA zona del mapa. Este modulo parte el area en celdas: cada celda es una
busqueda independiente, con su propio recuadro, y devuelve hasta 60 negocios
de ese barrio concreto.

Por que rectangulos y no circulos
---------------------------------
Text Search (New) solo acepta `locationRestriction` como RECTANGULO (viewport);
el circulo unicamente vale para `locationBias`, que es una preferencia blanda y
dejaria colarse negocios de fuera de la zona. Como aqui hace falta una frontera
dura para que cada celda traiga cosas distintas, se usan rectangulos.

Ventaja extra: los rectangulos teselan el plano sin huecos NI solapes, asi que
cada negocio cae en exactamente una celda y no se gastan requests repitiendo
zona.
"""
import math

# Metros por grado de latitud (practicamente constante en todo el planeta).
METROS_POR_GRADO_LAT = 111_320.0


def _metros_por_grado_lng(lat: float) -> float:
    """A mayor latitud los meridianos se juntan: un grado de longitud mide menos."""
    return METROS_POR_GRADO_LAT * math.cos(math.radians(lat))


def distancia_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia aproximada en metros. Suficiente a escala de ciudad."""
    dlat = (lat2 - lat1) * METROS_POR_GRADO_LAT
    dlng = (lng2 - lng1) * _metros_por_grado_lng((lat1 + lat2) / 2)
    return math.hypot(dlat, dlng)


def rectangulo_de(lat: float, lng: float, lado_km: float) -> dict:
    """
    Recuadro (viewport) centrado en un punto, con el formato que pide Google:
    low = esquina suroeste, high = esquina noreste.
    """
    medio_lat = (lado_km * 1000 / 2) / METROS_POR_GRADO_LAT
    medio_lng = (lado_km * 1000 / 2) / _metros_por_grado_lng(lat)
    return {
        "low": {"latitude": round(lat - medio_lat, 6),
                "longitude": round(lng - medio_lng, 6)},
        "high": {"latitude": round(lat + medio_lat, 6),
                 "longitude": round(lng + medio_lng, 6)},
    }


def radio_circunscrito_km(lado_km: float) -> float:
    """
    Radio del circulo que envuelve por completo la celda cuadrada.

    Lo usa el modo "categoria exacta" (Nearby Search), que solo acepta circulos.
    Se toma el circunscrito y no el inscrito para no dejar las esquinas fuera.
    """
    return (lado_km / 2) * math.sqrt(2)


def generar_celdas(
    lat_centro: float,
    lng_centro: float,
    radio_total_km: float,
    lado_celda_km: float,
) -> list[tuple[float, float]]:
    """
    Centros de las celdas que cubren el area de busqueda.

    Ordenadas de dentro hacia afuera: las zonas centrales suelen concentrar
    mas negocios, asi que se exploran primero y los mejores leads llegan antes.
    """
    radio_total_m = radio_total_km * 1000.0
    lado_m = lado_celda_km * 1000.0

    if lado_m >= radio_total_m * 2:
        return [(round(lat_centro, 6), round(lng_centro, 6))]

    grados_lat = lado_m / METROS_POR_GRADO_LAT
    grados_lng = lado_m / _metros_por_grado_lng(lat_centro)

    # Cuantas celdas hacen falta a cada lado para tapar el circulo entero.
    pasos = int(math.ceil(radio_total_m / lado_m)) + 1

    # La diagonal media de la celda: si el centro de la celda esta a mas de
    # (radio + media diagonal), la celda no toca el area y se descarta.
    media_diagonal_m = (lado_m / 2) * math.sqrt(2)

    celdas: list[tuple[float, float]] = []
    for fila in range(-pasos, pasos + 1):
        for columna in range(-pasos, pasos + 1):
            lat = lat_centro + fila * grados_lat
            lng = lng_centro + columna * grados_lng
            if distancia_m(lat_centro, lng_centro, lat, lng) <= radio_total_m + media_diagonal_m:
                celdas.append((round(lat, 6), round(lng, 6)))

    celdas.sort(key=lambda c: distancia_m(lat_centro, lng_centro, c[0], c[1]))
    return celdas


def lado_celda_recomendado(radio_total_km: float) -> float:
    """
    Tamano de celda sensato para el radio pedido.

    Celdas muy grandes desperdician resultados (cada una topa en 60 y el resto
    se pierde); celdas muy chicas disparan el numero de requests y el costo.
    """
    if radio_total_km <= 2:
        return radio_total_km * 2   # una sola celda
    if radio_total_km <= 6:
        return 2.0
    if radio_total_km <= 15:
        return 3.0
    if radio_total_km <= 30:
        return 4.0
    return 6.0
