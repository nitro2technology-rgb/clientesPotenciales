# Desplegar en Vercel — `scrapping.nitro2tech.com`

Todo lo de esta guía es gratuito: plan Hobby de Vercel + plan gratuito de Turso.

---

## Por qué hace falta Turso (y no solo Vercel)

En Vercel el disco es de **solo lectura** y se borra entre peticiones. La app
guarda en SQLite tres cosas que **no pueden perderse**:

| Qué | Qué pasa si se pierde |
|---|---|
| Histórico de negocios (627 ahora mismo) | Se repiten los mismos leads una y otra vez |
| Progreso de campañas | El barrido vuelve a empezar por el sector 1 |
| **Contador de requests del día** | **El tope de gasto se reinicia solo y deja de frenar** |

Turso es SQLite alojado: mismo dialecto, misma consulta, mismo `storage.py`.
El plan gratuito da 5 GB y 500 bases — esta ocupa menos de 1 MB.

**En tu PC no cambia nada.** Si `TURSO_DATABASE_URL` está vacía, la app usa
`data/leads.db` como siempre.

---

## Paso 1 — Crear la base en Turso

1. Entra en <https://turso.tech> y crea la cuenta (gratis, con GitHub o email).
2. **Create Database**. Nombre: `leads-nitro2tech`.
   Región: la más cercana a Colombia (`aws-us-east-1`).
3. Ya creada, en la pantalla de la base copia:
   - **Database URL** → algo como `libsql://leads-nitro2tech-tuusuario.turso.io`
   - **Create Token** (o *Generate Token*) → una cadena larga. **Se muestra
     una sola vez**, cópiala entera.

Pega las dos en el `.env`:

```
TURSO_DATABASE_URL=libsql://leads-nitro2tech-tuusuario.turso.io
TURSO_AUTH_TOKEN=eyJhbGciOi...
```

---

## Paso 2 — Subir tu histórico

```bash
cd "C:\Nico\Nitro2Tech\Scraping web"
.venv\Scripts\python.exe migrar_a_turso.py
```

Crea las tablas y sube negocios, búsquedas, campañas, celdas, geocaché y el
contador del día. Al final compara local contra Turso, tabla por tabla.

Es idempotente: puedes repetirlo sin miedo, no duplica.
**No toca `data/leads.db`** — el fichero local queda intacto como respaldo.

Comprobar en cualquier momento, sin subir nada:

```bash
.venv\Scripts\python.exe migrar_a_turso.py --verificar
.venv\Scripts\python.exe verificar.py          # ahora también chequea la base
```

---

## Paso 3 — Desplegar

El proyecto ya existe: **`scrapping-nitro2tech`**, en el equipo `nitro2-tech`,
con el repo `nitro2technology-rgb/clientesPotenciales` conectado.

### Si los despliegues automáticos se quedan en `UNKNOWN`

Pasó la primera vez: Vercel creaba el despliegue pero no podía clonar, sin logs
ni duración. Es que a su GitHub App le falta permiso sobre la organización.

`https://github.com/organizations/nitro2technology-rgb/settings/installations`
→ **Vercel** → **Configure** → dar acceso a `clientesPotenciales` → **Save**.

Después, en Vercel → *Deployments* → `···` → **Redeploy**, desmarcando *Use
existing Build Cache*.

---

## Paso 4 — Variables de entorno en Vercel

Vercel **no lee tu `.env`** (está en `.vercelignore`, y así debe ser). Hay que
declararlas. Desde la web: proyecto → *Settings* → *Environment Variables*.
Marca los tres entornos (Production, Preview, Development).

| Variable | Valor |
|---|---|
| `GOOGLE_MAPS_API_KEY` | tu API key de Google |
| `TURSO_DATABASE_URL` | la misma del paso 1 |
| `TURSO_AUTH_TOKEN` | el mismo del paso 1 |
| `DEMO_MODE` | `false` |
| `MAX_REQUESTS_PER_DAY` | `50` |
| `MAX_PAGES_PER_SEARCH` | `3` |
| `CELDAS_POR_SESION` | `5` |
| `CONFIRMAR_ANTES_DE_GASTAR` | `true` |

Google Sheets (ya configurado y verificado — hoja «Leads Google Maps»): en el
servidor no hay dónde dejar el `.json`, así que su contenido va en una
variable. Añade también:

| Variable | Valor |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | el contenido de `json de maps/service.json` |
| `GOOGLE_SHEET_ID` | `1xrpddOYXUIvi84oKFKiEdwfI49wJR65NYDEGqMYIS5I` |
| `GOOGLE_SHEET_TAB` | `Leads` |

**No hace falta aplanarlo a una línea**: Vercel acepta valores multilínea y
`json.loads` no distingue. Abre el archivo, copia todo y pega.

Tras añadirlas hay que volver a desplegar para que las tome:

```bash
vercel --prod
```

---

## Paso 5 — El dominio `scrapping.nitro2tech.com`

En Vercel: proyecto → *Settings* → *Domains* → *Add* → `scrapping.nitro2tech.com`.

El DNS de `nitro2tech.com` está en **Namecheap** (nameservers
`dns1/dns2.registrar-servers.com`, o sea BasicDNS). El registro se crea en:

**Domain List** → `nitro2tech.com` → **Manage** → pestaña **Advanced DNS** →
**Add New Record**:

| Type | Host | Value | TTL |
|---|---|---|---|
| `CNAME Record` | `scrapping` | `cname.vercel-dns.com` | Automatic |

En **Host va solo `scrapping`**, no el dominio entero: Namecheap le añade
`.nitro2tech.com` por su cuenta. Si Vercel muestra otro valor en su pantalla de
Domains, manda el suyo.

Propaga en minutos (a veces hasta una hora). El certificado HTTPS lo emite
Vercel solo.

---

## Paso 6 — La API Key de Google

**Esto es importante y es fácil que se pase por alto.** Si la key tiene
restricción **por dirección IP**, deja de funcionar: Vercel no tiene IP fija.

En Google Cloud Console → *APIs y servicios* → *Credenciales* → tu key:

- **Restricciones de aplicación**: quita la de IP. Ponla en *Ninguna*.
  (*Sitios web / HTTP referrers* no vale aquí: la key se usa desde el
  servidor, no desde el navegador, así que no viaja ningún referrer.)
- **Restricciones de API**: déjala limitada a **Places API (New)** y
  **Geocoding API**. Esta sí conviene mantenerla.

Como la key queda sin restricción de origen, el techo real de gasto pasa a ser
la **cuota de la Places API** y la **alerta de presupuesto** en Google Cloud.
Ponlas si aún no están:

- *Facturación* → *Presupuestos y alertas* → presupuesto de **$5** con avisos
  al 50 / 90 / 100 %.
- *APIs y servicios* → *Places API (New)* → *Cuotas* → límite diario de
  peticiones acorde a `MAX_REQUESTS_PER_DAY`.

---

## Aviso: la URL queda pública

`scrapping.nitro2tech.com` no pide contraseña. Cualquiera que dé con la
dirección puede pulsar Buscar y gastar tu saldo de Google (~$0,04 por
petición). Fue una decisión tomada a conciencia; queda anotada aquí.

Lo que sí sigue frenando:

- el tope diario `MAX_REQUESTS_PER_DAY` (ahora sí persiste, gracias a Turso);
- el modal de confirmación antes de gastar;
- la cuota y el presupuesto de Google Cloud — **este es el techo de verdad**.

Si algún día quieres cerrarla, lo más simple es un middleware de Basic Auth en
`app/main.py` leyendo usuario y clave de variables de entorno.

---

## Qué se tocó del código para que esto funcionara

| Archivo | Cambio |
|---|---|
| `app/turso.py` | **Nuevo.** Cliente de la API HTTP de Turso sobre `httpx`. Imita lo justo de `sqlite3` que usa `storage.py`. Sin dependencias nuevas (el paquete oficial `libsql-client` arrastra `sphinx` y `aiohttp` como dependencias de runtime). |
| `app/storage.py` | `conectar()` abre Turso o SQLite local según config. El SQL de las 20 consultas **no se tocó**. El esquema se crea una vez por proceso, ya no al importar. |
| `app/config.py` | Variables `TURSO_*` y `GOOGLE_SERVICE_ACCOUNT_JSON`. Ya no crea `data/` si la base es remota (reventaba en disco de solo lectura). |
| `app/sheets.py` | `from_service_account_info` en vez de `_file`: acepta credenciales desde variable de entorno. |
| `app/main.py` | `POST /api/descargar/{formato}` sin estado. Manejador de `ErrorTurso` → 503 con mensaje claro. |
| `static/app.js` | La descarga manda las filas que ya están en pantalla en vez de pedirlas por id. |
| `api/index.py` | **Nuevo.** Punto de entrada de Vercel. |
| `vercel.json` | **Nuevo.** Todas las rutas a la función; `maxDuration` 60 s. |
| `.vercelignore` | **Nuevo.** Fuera `.venv`, `.env`, `credentials/`, `data/`. |
| `migrar_a_turso.py` | **Nuevo.** Sube `leads.db` a Turso. Idempotente. |
| `verificar.py` | Comprueba también la base de datos. |

### Por qué la descarga cambió

Antes el botón pedía `busqueda_id=ultima` y el servidor lo resolvía con un
diccionario en memoria. En Vercel cada petición puede caer en una instancia
distinta, así que ese diccionario suele estar vacío y la descarga daría 404.
Ahora el navegador reenvía las filas que ya tiene pintadas: funciona siempre,
incluso con «guardar» desactivado. El `GET` sigue existiendo para descargar el
histórico completo desde la base.

---

## Trampas del despliegue

**Los 60 segundos de la función.** Plan Hobby: una petición no puede durar
más. Un barrido de 5 sectores × 3 páginas son 15 llamadas a Google en serie.
Va justo. Si ves errores `FUNCTION_INVOCATION_TIMEOUT`, baja *Sectores* a 2 o 3
en Opciones avanzadas.

**Latencia por consulta.** Cada consulta a Turso es un viaje de red (~30 ms)
en vez de una lectura de disco. Se nota en `/api/campanas`, no en el uso normal.

**El `.env` no viaja.** Si algo funciona en local y no desplegado, lo primero
que hay que mirar es si esa variable está declarada en Vercel.

**Redesplegar tras cambiar variables.** Vercel no las aplica a un despliegue ya
hecho: hay que lanzar `vercel --prod` otra vez.

**El fichero local ya no se actualiza** una vez que la app en la nube es la que
usas. `data/leads.db` queda congelado como respaldo del día de la migración.
