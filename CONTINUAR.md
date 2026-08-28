# Continuar aquí — Generador de Leads desde Google Maps

> Última sesión: **27 de agosto de 2026**
> Estado: **código listo para desplegar en Vercel. Falta la primera búsqueda
> real contra Google y faltan credenciales en el `.env`.**

---

## Lo que quedó pendiente

### 1. El `.env` está vacío de credenciales

Ojo: la sesión anterior dio por hecho que estaban puestas, y **no lo están**.
Comprobado el 27 de agosto:

- `GOOGLE_MAPS_API_KEY=` — **vacía**. Sin esto ninguna búsqueda funciona.
  La clave parece estar en `Claves appi.txt`.
- `GOOGLE_SERVICE_ACCOUNT_FILE=` y `GOOGLE_SHEET_ID=` — vacías. Google Sheets
  **no está conectado**, aunque la tabla de más abajo lo diera por hecho. No es
  grave: es opcional y la app guarda igual en local y exporta a Excel/CSV.

Para ver el estado real en cualquier momento, sin gastar un céntimo:

```bash
.venv\Scripts\python.exe verificar.py
```

### 2. Nunca se ha ejecutado una búsqueda real contra Google

Todo se validó en modo demo y con respuestas simuladas.

### 3. El despliegue está preparado pero sin lanzar

Ver **[DEPLOY.md](DEPLOY.md)**: Vercel + Turso, gratis, para
`scrapping.nitro2tech.com`. El código ya está adaptado y probado en local; solo
faltan los pasos que requieren tus cuentas (crear la base en Turso, `vercel
login`, y el CNAME en el DNS de `nitro2tech.com`).

### Cómo retomar (5 minutos)

```bash
cd "C:\Nico\Nitro2Tech\Scraping web"

# 1. Comprobar credenciales — NO gasta dinero
.venv\Scripts\python.exe verificar.py

# 2. Arrancar
.venv\Scripts\python.exe run.py
```

Abre <http://127.0.0.1:8000>

### La primera búsqueda de prueba (deliberadamente mínima)

En *Opciones avanzadas*: **Sectores = 2**, **Páginas máximo = 1**, y
**desmarca** rating/reseñas.

- Ciudad: `Bogotá, Colombia`
- Tipo: `veterinarias`
- Radio: **2 km**

Son ~3 requests (~$0.13). El modal de confirmación te lo dirá antes de llamar.

**Qué revisar cuando termine:**
1. ¿Salieron negocios reales con teléfono y dirección?
2. ¿Los marcados como lead de verdad no tienen web (o solo Facebook/Instagram)?
3. ¿Aparecieron las filas en el Google Sheet?
4. ¿El Excel descargado abre bien?

Si algo falla, el mensaje de error en pantalla dice qué revisar. Los errores de
Google (403, API no habilitada, key restringida) traen instrucciones concretas.

Si sale bien: sube a 5 sectores y 3 páginas, y ya puedes barrer en serio.

---

## Qué hace la app

Busca negocios en Google Maps por ciudad + radio + categoría y marca como
**lead válido** al que:
- no tiene web en su ficha de Maps, **o**
- su "web" es un perfil de red social (Facebook, Instagram…).

Los que tienen dominio propio se guardan igual, marcados como "Ya tiene sitio
web propio" — no se ocultan.

---

## Estado por pieza

| Pieza | Estado | Cómo se verificó |
|---|---|---|
| Clasificación de leads | Listo | Probado con web vacía, Facebook, Instagram, subdominios y dominio propio |
| Places API + field masking | Listo, sin estrenar | Probado con respuestas simuladas de Google (paginación, 403, ciudad inexistente) |
| Google Sheets | Código listo, **sin credenciales** | `verificar.py` prueba conexión y escritura cuando las hay |
| Excel / CSV | Listo | Se abre el .xlsx generado y se comprueban colores, autofiltro y links |
| Deduplicación por Place ID | Listo | Repetir búsqueda → 0 filas nuevas |
| Barrido progresivo | Listo | Campaña agotada entera: 222 negocios únicos, **0 repetidos** |
| Rejilla de sectores | Listo | 5.000 puntos aleatorios: 0 sin cubrir, 0 en dos sectores a la vez |
| Confirmación de costo | Listo | Probado confirmar, cancelar y Escape |
| Control de cuota diaria | Listo | Bloquea al llegar al tope y cuenta también los requests fallidos |

---

## Mapa del código

```
app/
  main.py            Endpoints FastAPI
  campaign.py        Barrido: qué sector toca ahora + filtro de ya conocidos
  grid.py            Rejilla de sectores (rectángulos que teselan)
  places.py          Cliente Places API + Geocoding, field masking, cuota
  classifier.py      La regla: ¿es lead o no?
  social_domains.py  <- LISTA_REDES_SOCIALES (editar aquí para ampliar)
  storage.py         SQLite: histórico, dedupe, campañas, contador, geocaché
  sheets.py          Google Sheets (opcional, nunca tumba una búsqueda)
  exports.py         .xlsx y .csv
  config.py          Lee el .env
static/              Frontend (HTML+CSS+JS, sin frameworks)
verificar.py         Chequeo de credenciales a costo cero
run.py               Lanzador
data/leads.db        Histórico local (ignorado por git)
```

---

## Decisiones ya tomadas (no hay que volver a discutirlas)

**El límite de 60 resultados es de Google, no del código.** Text Search devuelve
como máximo 3 páginas de 20. Confirmado en la documentación oficial. No hay
constante que subir.

**Repetir la misma consulta mañana devuelve los mismos 60.** No existe
"continuar desde donde quedé" entre sesiones. Por eso el barrido progresivo
cambia *dónde* busca, en vez de pedir más de lo mismo.

**Los sectores usan `locationRestriction` rectangular, no circular.** Text
Search solo acepta rectángulos ahí. El círculo únicamente vale para
`locationBias`, que es una preferencia blanda: con Bias, al buscar en un barrio
periférico Google devuelve igualmente los del centro y el barrido no traería
nada nuevo. (Esto ya se implementó mal una vez — no volver a intentarlo con
círculos.)

**Google Places no expone emails.** La columna existe vacía a propósito. Sacar
emails exigiría visitar la web de cada negocio, y eso solo aplica a los que
*sí* tienen web, que no son el objetivo.

**Nunca se hace scraping del HTML de Google Maps.** Viola los Términos de
Servicio y puede bloquear la cuenta.

---

## Trampas conocidas

**Los precios en pantalla son estimaciones mías**, no datos de Google. Están en
`app/places.py` → `PRECIO_BUSQUEDA_BASE` (40), `PRECIO_BUSQUEDA_RATING` (45),
`PRECIO_GEOCODING` (5), todos por 1000 requests. Verificar en
<https://mapsplatform.google.com/pricing/> y ajustar.

**Las salvaguardas locales no reemplazan a Google Cloud.** Sigue pendiente
confirmar que están puestas la alerta de presupuesto ($5) y la cuota diaria de
la Places API en la consola. Eso es el techo real.

**`MAX_REQUESTS_PER_DAY=50`** es un valor conservador para las primeras
pruebas. Una sesión de 10 sectores × 3 páginas son 30 requests: se agota rápido.
Subirlo en `.env` cuando haya confianza.

**En modo demo no se escribe en el Google Sheet** (protección deliberada, para
no mezclar datos inventados con leads reales). Si algún día el Sheet "no recibe
nada", lo primero que hay que mirar es si `DEMO_MODE` quedó en `true`.

**El puerto 8000 se queda ocupado** si un servidor anterior no murió bien. Para
liberarlo:
```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

---

## Ideas para después

- **Barrido automático desatendido**: dejar corriendo N sesiones seguidas con
  pausa entre ellas, respetando la cuota diaria. Hoy hay que pulsar Buscar cada
  vez.
- **Varias palabras clave por campaña**: hoy `abogados` y `bufete` son campañas
  separadas. Podrían encadenarse en una sola pasada.
- **Panel de campañas en la interfaz**: el endpoint `/api/campanas` ya devuelve
  todas con su progreso, pero no hay pantalla que las liste.
- **Extracción de emails** (fuera del alcance de la v1): visitar la web de los
  negocios que sí tienen una y sacar el correo.
- ~~**Deploy en Render o Railway**~~ → resuelto con **Vercel + Turso**, ver
  [DEPLOY.md](DEPLOY.md). Sigue pendiente quitar la restricción por IP de la
  API Key: Vercel no tiene IP fija.
- **Proteger la URL con contraseña**: `scrapping.nitro2tech.com` queda pública
  y sin login. Decisión tomada a conciencia, pero cualquiera que dé con la
  dirección puede gastar saldo de Google. Un middleware de Basic Auth en
  `app/main.py` leyendo dos variables de entorno lo cerraría.

---

## Recordatorio de seguridad

Las credenciales viven **solo** en `.env` y en el JSON de la service account.
Ambos están cubiertos por `.gitignore` (verificado con un repo de prueba: git
solo subiría README, código y `.env.example`).

Si algún día se conecta un repositorio real, **antes** de subir nada:
```bash
git status --porcelain     # revisar que no aparezcan .env ni ningún .json
```
