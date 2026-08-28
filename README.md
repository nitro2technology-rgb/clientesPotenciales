# Generador de Leads desde Google Maps

Busca negocios en Google Maps por **ciudad + radio + categoría** y detecta
automáticamente cuáles **no tienen página web propia** — es decir, cuáles son
clientes potenciales para venderles una.

Un negocio es **lead válido** si:
- no tiene ningún sitio web en su ficha de Google Maps, **o**
- su "sitio web" es en realidad un perfil de red social (Facebook, Instagram…).

Si tiene un dominio propio, se guarda igual pero marcado como *"Ya tiene sitio
web propio"* (no se oculta, para que puedas revisarlo).

---

## Arranque rápido (modo demo, sin gastar un peso)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows.  En Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # Mac/Linux: cp .env.example .env
# En .env deja DEMO_MODE=true  -> datos de ejemplo, NO se llama a Google

python run.py
```

Abre **http://127.0.0.1:8000**. Con `DEMO_MODE=true` puedes probar toda la
interfaz, los filtros y las descargas sin tocar tu cuenta de Google Cloud.

Cuando ya tengas la API Key: pégala en `.env` y cambia a `DEMO_MODE=false`.

---

## Cómo se usa

1. Escribe la **ciudad** ("Bogotá, Colombia"), el **tipo de negocio**
   ("peluquerías") y mueve el **radio**.
2. *Opciones avanzadas* te deja elegir:
   - **Modo palabra clave** — hasta 60 resultados (3 páginas). El recomendado.
   - **Modo categoría exacta** — usa los tipos oficiales de Google, máx. 20.
   - **Páginas máximo** — cada página son ~20 negocios y cuesta 1 request.
   - **Rating y reseñas** — útil para priorizar, sube un poco el costo.
3. Pulsa **Buscar negocios**. Verás el conteo de leads y la tabla.
4. Filtra entre *Solo leads* / *Todos* / *Ya tienen web*.
5. **Descargar Excel** o **CSV** (respeta el filtro activo).

Los resultados se guardan siempre en el histórico local (`data/leads.db`) y, si
lo configuraste, también en tu Google Sheet.

---

## Ampliar la lista de redes sociales

Todo está en un solo archivo: **`app/social_domains.py`**.

```python
LISTA_REDES_SOCIALES = {
    "facebook.com", "fb.com", "fb.me", "fb.watch",
    "instagram.com", "instagr.am",
}
```

Debajo hay un bloque `CANDIDATOS_OPCIONALES` ya escrito y listo para copiar:
`wa.me`, `whatsapp.com`, `linktr.ee`, `linkr.bio`, `beacons.ai`, `tiktok.com`,
`business.site`, `wixsite.com`… Mueve al primer bloque los que quieras activar
y reinicia la app.

Los subdominios se detectan solos: `m.facebook.com` y `es-la.facebook.com`
hacen match con `facebook.com`.

---

## Control de costos (lo que protege tu tarjeta)

La app trae cinco salvaguardas:

| Salvaguarda | Dónde | Qué hace |
|---|---|---|
| **Confirmación antes de gastar** | `.env` → `CONFIRMAR_ANTES_DE_GASTAR` | Antes de cada búsqueda real, muestra una ventana con el desglose del costo y hay que pulsar "Sí, buscar y gastar". Cancelar no gasta nada. |
| **Field Masking** | `app/places.py` → `CAMPOS_BASE` | Pide solo 9 campos. Pedir de más sube el precio por request. |
| **Tope diario duro** | `.env` → `MAX_REQUESTS_PER_DAY` | Al llegar al tope, la app se bloquea sola y devuelve error 429. Contador en `data/leads.db`. |
| **Tope de páginas** | `.env` → `MAX_PAGES_PER_SEARCH` | Impide que una búsqueda dispare requests sin control. |
| **Caché de geocoding** | `app/storage.py` | La misma ciudad se geocodifica una sola vez, nunca se vuelve a pagar. |

Además, la interfaz muestra **antes** de buscar cuántos requests gastarás y el
costo estimado, y **después** cuántos requests te quedan hoy. El contador se
actualiza incluso si la búsqueda falla, porque un request rechazado por Google
igual consume cuota.

> Los precios en pantalla son una **estimación** (`PRECIO_BUSQUEDA_*` en
> `app/places.py`). Google cambia sus tarifas: verifica las reales en
> <https://mapsplatform.google.com/pricing/> y ajusta esas constantes.
> Google también incluye un cupo gratuito mensual por SKU — revisa el tuyo en
> la consola.

**Esto no reemplaza** configurar la alerta de presupuesto y las cuotas en
Google Cloud (paso 6 de abajo). Hazlo igual.

---

## Dónde va cada credencial

Las tres van en el archivo **`.env`** (en la raíz del proyecto). Ese archivo ya
está en `.gitignore`, verificado: git no lo subiría nunca.

| Qué tienes | Variable en `.env` | Qué se pega |
|---|---|---|
| API Key | `GOOGLE_MAPS_API_KEY` | La clave completa (`AIza...`) |
| JSON de la Service Account | `GOOGLE_SERVICE_ACCOUNT_FILE` | La **ruta al archivo**, no su contenido |
| ID del Sheet | `GOOGLE_SHEET_ID` | El código entre `/d/` y `/edit` de la URL |

Sin comillas y sin espacios alrededor del `=`. En rutas de Windows usa barras
normales (`C:/Users/...`). El JSON conviene moverlo a `credentials/`, que ya
está ignorada por git.

Después de pegarlas, comprueba que quedaron bien **sin gastar dinero**:

```bash
python verificar.py
```

Valida el formato de la API Key, que el JSON exista y esté completo, te dice el
email de la service account (el que debes autorizar en el Sheet) y prueba la
conexión y la **escritura** en el Sheet. La API de Sheets no cobra, así que esa
prueba es gratis. Places y Geocoding no se llaman ahí: esas sí costarían.

---

## Configurar Google Cloud (paso a paso)

Esto solo lo puedes hacer tú, con tu cuenta.

### 1. Proyecto y facturación
1. Entra a <https://console.cloud.google.com/> y crea un proyecto
   (ej: `leads-maps`).
2. Activa facturación con tarjeta. Es obligatorio para usar la API, aunque no
   te cobre mientras estés dentro del crédito/cupo gratuito.

### 2. Habilitar las APIs
En *APIs y servicios → Biblioteca*, habilita:
- **Places API (New)** ← ojo, la "New", no la clásica
- **Geocoding API**
- **Google Sheets API** (solo si vas a usar el Sheet)

### 3. Crear y restringir la API Key
1. *APIs y servicios → Credenciales → Crear credenciales → Clave de API*.
2. Cópiala y pégala en `.env` como `GOOGLE_MAPS_API_KEY=...`
3. **Restríngela** (importante): edita la clave y en
   *Restricciones de aplicación* elige **Direcciones IP** con la IP de tu
   servidor mientras corras en local o en Render/Railway. En
   *Restricciones de API* deja solo Places API (New) y Geocoding API.

> La API Key va en `.env`, que ya está en `.gitignore`. Nunca la subas a un
> repositorio ni la pegues en el código.

### 4. Alerta de presupuesto
*Facturación → Presupuestos y alertas → Crear presupuesto*: monto **5 USD**,
alertas al 50 %, 90 % y 100 % a tu correo.

### 5. Cuotas duras (el techo real)
*APIs y servicios → Places API (New) → Cuotas*: baja el límite de
*requests por día* a algo que te sirva (ej: 200). Aunque falle todo lo demás,
Google no te dejará pasar de ahí.

### 6. Google Sheets (opcional)
1. *IAM y administración → Cuentas de servicio → Crear cuenta de servicio*.
2. Crea una clave **JSON** y descárgala. Guárdala fuera del repo o en
   `credentials/` (ya ignorado por git).
3. Crea un Google Sheet y **compártelo como Editor** con el email de la cuenta
   de servicio (algo como `leads@tu-proyecto.iam.gserviceaccount.com`).
4. En `.env`:
   ```
   GOOGLE_SERVICE_ACCOUNT_FILE=C:/ruta/a/credenciales.json
   GOOGLE_SHEET_ID=<el id largo que sale en la URL del Sheet>
   GOOGLE_SHEET_TAB=Leads
   ```

Si no configuras esto, **la app funciona igual**: guarda en SQLite local y
exporta a Excel/CSV. El Sheet solo agrega la comodidad de verlo desde el
celular.

---

## Estructura del proyecto

```
app/
  main.py            FastAPI: endpoints de búsqueda, campañas, histórico y descargas
  campaign.py        Barrido progresivo: qué sector toca ahora y filtro de ya conocidos
  grid.py            Rejilla de sectores que cubre la ciudad sin huecos ni solapes
  places.py          Cliente Places API (New) + Geocoding · field masking · cuota
  classifier.py      La regla de negocio: ¿es lead o no?
  social_domains.py  <- LISTA_REDES_SOCIALES (edita aquí)
  storage.py         SQLite: histórico, dedupe por Place ID, contador, geocaché
  sheets.py          Escritura en Google Sheets (opcional, nunca tumba la búsqueda)
  exports.py         Generación de .xlsx y .csv
  models.py          Modelos Pydantic
  config.py          Lectura del .env
static/              Frontend (HTML + CSS + JS, sin frameworks)
data/leads.db        Histórico local (ignorado por git)
run.py               Lanzador
```

### Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/estado` | Config actual, consumo del día, lista de redes sociales |
| POST | `/api/campana/buscar` | **Barrido progresivo.** Explora los siguientes sectores y devuelve solo negocios nuevos. Query: `max_celdas`, `incluir_rating`, `guardar` |
| GET | `/api/campana/estado` | Progreso de una campaña (gratis, no llama a Google). Query: `ciudad`, `categoria`, `modo` |
| GET | `/api/campanas` | Todas las campañas con su progreso |
| POST | `/api/campana/reiniciar` | Vuelve a marcar todos los sectores como pendientes |
| POST | `/api/buscar` | Búsqueda suelta de un tiro (máx. 60). Query: `incluir_rating`, `guardar` |
| GET | `/api/historico` | Todo lo acumulado. Query: `limite`, `solo_leads` |
| GET | `/api/descargar/{xlsx\|csv}` | Query: `busqueda_id` (`ultima` / `historico` / un id), `solo_leads` |

Documentación interactiva en `/docs`.

---

## Barrido progresivo: sacar más de 60 sin repetir

**El problema:** la Places API devuelve como máximo 60 resultados por consulta,
y si repites la misma consulta mañana te devuelve **los mismos 60** — el ranking
de relevancia no cambia y no existe un "dame los siguientes 60".

**La solución:** el barrido progresivo (activado por defecto). La primera vez
que buscas una ciudad + categoría, la app parte la zona en **sectores** y los
guarda como pendientes. Cada vez que pulsas Buscar, explora los siguientes
sectores sin visitar — nunca los mismos. Así:

```
Día 1  →  sectores 1-5    →  30 negocios nuevos
Día 2  →  sectores 6-10   →  28 negocios nuevos   (ninguno repetido)
Día 3  →  sectores 11-15  →  31 negocios nuevos
...
Día N  →  "Zona explorada por completo"
```

La barra de progreso te dice en todo momento cuántos sectores llevas y cuántos
quedan. Cuando llega al 100 %, Google ya no tiene más para esa combinación.

**Doble filtro contra duplicados:**
1. Los sectores ya explorados no se vuelven a visitar (no se gastan requests).
2. Todo lo que vuelve se compara contra los Place ID guardados, así que en
   pantalla solo aparecen negocios que no tenías.

### Detalles técnicos

Cada sector se busca con `locationRestriction` **rectangular** — una frontera
dura. No se usa `locationBias` (circular) porque es solo una preferencia: al
buscar en un barrio periférico, Google devolvería igualmente los negocios del
centro y el barrido no traería nada nuevo. Text Search además **solo acepta
rectángulos** en `locationRestriction`.

Los rectángulos teselan el plano sin huecos ni solapes, así que cada negocio
cae en exactamente un sector.

El tamaño del sector se elige solo según el radio (`app/grid.py` →
`lado_celda_recomendado`): 2 km para radios cortos, hasta 6 km para 50 km.

### Cuánto cuesta

Cada sector cuesta hasta `MAX_PAGES_PER_SEARCH` requests. Con los valores por
defecto (5 sectores × 3 páginas) son **15 requests por sesión**. Ajusta:

- `.env` → `CELDAS_POR_SESION` — tope de sectores por búsqueda
- En pantalla, *Opciones avanzadas* → **Sectores por búsqueda** (2 / 5 / 10)

El modal de confirmación siempre te muestra el total antes de gastar, y nunca
cobra por sectores que ya no quedan pendientes.

### Cuando la zona se agota

Cuando la barra llega al 100 %, tienes tres caminos:

- **Otra palabra clave** para el mismo oficio: `bufete`, `asesoría jurídica`,
  `abogado laboral`. Cada una es una campaña independiente y saca negocios que
  la anterior no encontró.
- **Ampliar el radio** — se recalcula la rejilla con los sectores nuevos.
- **Reiniciar la campaña** (`POST /api/campana/reiniciar`) meses después, para
  recapturar negocios que abrieron desde entonces. Los Place ID ya guardados se
  siguen filtrando: no se duplica nada.

### Búsqueda suelta

Si desactivas el barrido, vuelve al comportamiento de un solo tiro: una
consulta, máximo 60 resultados, sin memoria de progreso. Útil para sondear
rápido una zona antes de lanzar una campaña completa.

---

## Deduplicación

Cada negocio se guarda con su **Place ID**. Antes de insertar, se compara
contra los que ya existen — tanto en SQLite como en el Sheet. Si vuelves a
buscar lo mismo mañana, no se duplican filas: solo entran los negocios nuevos.

En **modo demo nunca se escribe en tu Google Sheet real**, para que los datos
de ejemplo no se mezclen con tus leads de verdad.

---

## Notas y límites conocidos

- **No hay emails.** La Places API no los expone. La columna existe en el
  Excel y en el Sheet, vacía, para que la llenes a mano o para una versión
  futura que visite la web del negocio.
- **Máx. 60 resultados por consulta** (límite de Google: 3 páginas de 20).
  El barrido progresivo lo sortea repartiendo la ciudad en sectores, pero el
  tope de 60 sigue aplicando *a cada sector*.
- **Máx. 20 resultados** en modo categoría exacta (Nearby Search no pagina).
- **Radio máximo 50 km** (límite de la API).
- No se hace scraping del HTML de Google Maps: eso viola los Términos de
  Servicio y puede bloquear tu cuenta.

---

## Fuera de alcance en esta versión

Extracción automática de emails, envío de mensajes a los leads, integración con
WhatsApp Business API y multi-usuario con login.
