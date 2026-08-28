# Proyecto: Generador de Leads desde Google Maps (para venta de páginas web)

## 1. Objetivo del proyecto

Construir una aplicación web que permita buscar negocios en Google Maps por
**ciudad**, **radio** y **categoría/tipo de negocio**, y que identifique
automáticamente cuáles son **clientes potenciales** para servicios de
creación de páginas web.

Un negocio se considera **lead válido** (candidato a cliente) si cumple
CUALQUIERA de estas condiciones:

- **No tiene ningún sitio web registrado** en su ficha de Google Maps.
- **Sí tiene un "sitio web" registrado, pero es en realidad un perfil de
  red social** y no una página web propia. Se debe marcar como lead válido
  si el campo "website" contiene alguno de estos dominios (no es lista
  cerrada, debe ser fácil de ampliar):
  - `facebook.com`, `fb.com`, `fb.me`
  - `instagram.com`
  - (dejar preparado para añadir fácilmente: `wa.me` / `whatsapp.com` si solo
    tienen link de WhatsApp, `linktr.ee`, `linkr.bio`, etc. — el usuario
    decidirá si los agrega más adelante)

Si el "website" es un dominio propio distinto a los anteriores, el negocio
**NO** es un lead válido (ya tiene página web) y se descarta o se marca
como "no aplica" (ver sección 4, se recomienda igual guardarlo pero marcado,
no ocultarlo silenciosamente).

## 2. Fuente de datos

Usar la **Google Places API (New)** de Google Cloud (no hacer scraping
directo del HTML de Google Maps, porque viola los Términos de Servicio de
Google, es inestable y puede bloquear la cuenta/IP).

Endpoints relevantes:
- **Text Search / Nearby Search** — para buscar negocios por ciudad + radio
  + tipo de negocio (categoría).
- **Place Details** — para obtener el detalle de cada negocio encontrado
  (teléfono, sitio web, dirección, rating, etc.)

### Campos a solicitar (usar Field Masking para controlar el costo)

Del resultado de cada negocio, pedir SOLO estos campos (para minimizar el
costo por request, ya que Google cobra por "tier" de campos solicitados):

- `id` (Place ID, para evitar duplicados en futuras búsquedas)
- `displayName` (nombre del negocio)
- `formattedAddress` (dirección)
- `internationalPhoneNumber` o `nationalPhoneNumber` (teléfono)
- `websiteUri` (sitio web, si existe)
- `types` / `primaryType` (categoría del negocio)
- `rating` y `userRatingCount` (opcional, útil para priorizar leads con
  buena reputación pero sin web)
- `googleMapsUri` (link directo a la ficha en Google Maps, para que el
  usuario pueda verificar el negocio con un clic)

**Nota sobre el email:** Google Places API **no expone correos
electrónicos**. Dejar el campo "email" vacío en la base de datos salvo que
más adelante se agregue un paso opcional de visitar la web del negocio (si
tiene una que no sea red social) y extraer el email de ahí con un scraper
simple (fuera del alcance de la primera versión).

## 3. Lógica de negocio (pseudo-código)

```
para cada negocio encontrado en la búsqueda:
    website = negocio.websiteUri  (puede venir vacío / None)

    si website es vacío:
        es_lead = True
        motivo = "Sin sitio web"
    sino si dominio_de(website) pertenece a LISTA_REDES_SOCIALES:
        es_lead = True
        motivo = f"Sitio web es solo red social ({dominio})"
    sino:
        es_lead = False
        motivo = "Ya tiene sitio web propio"

    guardar_en_base_de_datos(negocio, es_lead, motivo)
```

`LISTA_REDES_SOCIALES` debe ser una constante fácil de editar en el código
(no hardcodeada en muchos lugares), por ejemplo un archivo de configuración
o un arreglo al inicio del script, ya que el usuario querrá ampliarla.

## 4. Almacenamiento de datos

Usar **Google Sheets** como base de datos (más simple que montar una base
de datos tradicional, y le permite al usuario ver/editar los datos desde su
celular o computador sin nada adicional).

- Un Google Sheet con una **hoja por búsqueda** o una sola hoja acumulativa
  con columna de "fecha de búsqueda" y "ciudad/parámetros usados" (a
  decidir en la fase de diseño técnico — el usuario prefiere poder ver
  histórico y no perder búsquedas anteriores).
- Columnas sugeridas:
  1. Fecha de búsqueda
  2. Ciudad
  3. Categoría buscada
  4. Nombre del negocio
  5. Dirección
  6. Teléfono
  7. Sitio web (si tiene, aunque sea red social)
  8. ¿Es lead? (Sí/No)
  9. Motivo (Sin sitio web / Solo red social: X / Ya tiene sitio propio)
  10. Rating
  11. Cantidad de reseñas
  12. Link de Google Maps
  13. Email (vacío por ahora, columna reservada a futuro)
  14. Estado de contacto (columna vacía para que el usuario la llene
      manualmente: "Contactado", "No contactado", "Cerrado", etc.)
  15. Place ID (oculto/técnico, para evitar duplicados)

**Evitar duplicados:** antes de insertar un negocio nuevo, verificar si su
`Place ID` ya existe en el Sheet. Si ya existe, no lo agregues no vuelvas
duplicar la fila (opcional: actualizar datos si cambiaron).

También se debe poder **descargar los resultados como archivo Excel
(.xlsx) o CSV** directamente desde la web app, sin depender de abrir Google
Sheets manualmente.

## 5. Aplicación web (frontend + backend)

### Frontend (interfaz que usará el usuario final, o sea, tú)

Una página web simple donde el usuario pueda:

- Escribir o seleccionar una **ciudad** (texto libre, ej: "Bogotá,
  Colombia").
- Definir un **radio de búsqueda** (en km o metros, con un selector o
  input numérico).
- Elegir el **tipo de negocio / categoría** (ej: restaurantes, peluquerías,
  gimnasios, veterinarias, ferreterías, etc. — usar las categorías que
  soporta la Places API, o un campo de texto libre tipo "keyword").
- Botón "Buscar negocios" que dispara el proceso de búsqueda.
- Ver una tabla en pantalla con los resultados de la última búsqueda
  (filtrando por defecto a "Solo leads válidos", con opción de ver todos).
- Botón para **descargar el Excel/CSV** de los resultados.
- Link visible al Google Sheet completo (histórico acumulado).
- Mostrar cuántos resultados se encontraron y cuántos son leads válidos.

### Backend

- Recibe los parámetros (ciudad, radio, categoría) desde el frontend.
- Convierte la ciudad en coordenadas (lat/lng) usando la Geocoding API de
  Google (o el propio Text Search de Places, que acepta texto de
  ubicación).
- Llama a la Places API (Nearby Search / Text Search + Place Details) con
  esos parámetros.
- Aplica la lógica de la sección 3 para clasificar cada negocio.
- Escribe los resultados nuevos (evitando duplicados) en el Google Sheet
  vía la Google Sheets API.
- Genera el archivo Excel/CSV para descarga.
- Expone un endpoint para "descargar último resultado".

### Stack técnico sugerido (a confirmar con el usuario)

- Backend: **Python (FastAPI o Flask)** — más simple para trabajar con
  Google APIs, pandas, y generación de Excel (openpyxl).
- Frontend: HTML/CSS/JS simple (no hace falta framework pesado), o un
  framework ligero si se prefiere.
- Autenticación con Google Sheets: **Service Account** de Google Cloud
  (así el backend puede escribir en el Sheet sin pedir login interactivo
  cada vez).
- Hosting: **Render** o **Railway** (free tier) para el backend, o todo
  junto en un solo servicio si el framework lo permite.

## 6. Control de costos / seguridad de la cuenta de Google Cloud

Esto es una prioridad del usuario: **evitar cualquier cobro inesperado**.

- Usar **Field Masking** en todas las llamadas a Places API (pedir solo
  los campos listados en la sección 2).
- Configurar en Google Cloud Console:
  - Una **alerta de presupuesto** (Budget Alert) en un monto bajo (ej: $5
    USD) que avise por correo si se acerca ese gasto.
  - **Cuotas diarias/mensuales** (quotas) en la API de Places para poner un
    techo duro a la cantidad de requests posibles, como salvaguarda extra.
- Guardar la API Key como variable de entorno (nunca hardcodeada en el
  código ni subida a un repositorio público).
- Restringir la API Key en Google Cloud Console para que solo funcione
  desde el dominio/servidor donde esté alojada la app (restricción por
  referer o por IP, según corresponda).

## 7. Fuera de alcance (para versiones futuras, no para la v1)

- Extracción automática de emails visitando la web del negocio (solo
  aplicaría a negocios que sí tienen web propia, que no son el target
  principal).
- Envío automático de mensajes/emails a los leads (esto además tiene
  implicaciones legales de spam/protección de datos que habría que revisar
  aparte).
- Integración con WhatsApp Business API para contacto directo.
- Multi-usuario / login (por ahora es una herramienta de uso personal).

## 8. Checklist de lo que el usuario (Nitro) debe hacer en Google Cloud

Esto no lo puede hacer Claude por el usuario, requiere su cuenta personal:

1. Crear una cuenta / proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Habilitar facturación (billing) con una tarjeta — no cobra hasta pasar
   el crédito gratuito, pero es obligatorio para poder usar la API.
3. Habilitar estas APIs en el proyecto:
   - Places API (New)
   - Geocoding API
   - Google Sheets API
4. Crear una **API Key** (para Places/Geocoding) y restringirla.
5. Crear una **Service Account** con permisos de editor sobre un Google
   Sheet específico (compartir el Sheet con el email de la service
   account), y descargar su archivo de credenciales JSON.
6. Configurar la alerta de presupuesto mencionada en la sección 6.

Claude puede guiar paso a paso cada uno de estos puntos cuando el usuario
esté listo para hacerlo.
