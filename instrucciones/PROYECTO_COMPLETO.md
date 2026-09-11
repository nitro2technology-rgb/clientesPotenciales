# Proyecto de scraping de leads — documentación completa

> Escrito el **11 de septiembre de 2026**, leyendo el código línea por línea y
> consultando la base de datos y el Google Sheet en vivo.
> Objetivo: que puedas pedir modificaciones sabiendo exactamente qué pieza toca.

---

## 1. Qué hace, en una frase

Busca negocios en Google Maps por ciudad, categoría y radio, marca como **lead
válido** a los que no tienen página web propia, y los va acumulando sin
repetirse en una base de datos y en un Google Sheet.

Un negocio es **lead** cuando:

- su ficha de Maps no tiene sitio web, **o**
- su "sitio web" es un perfil de red social (hoy: Facebook e Instagram).

Los que sí tienen dominio propio **no se descartan**: se guardan marcados como
"Ya tiene sitio web propio", para no volver a pagar por descubrirlos.

Son **dos páginas** sobre la misma base de datos:

- `/` — el buscador, que sale a Google Maps y gasta dinero.
- `/crm` — el seguimiento, para llamar a esos negocios y anotar qué pasó.
  No llama a Google, así que usarla no cuesta nada.

---

## 2. Estado real hoy

Leído en vivo el 11 de septiembre de 2026.

| Dato | Valor |
|---|---|
| Negocios acumulados en la base | 3.725 |
| De ellos, leads válidos | 1.768 |
| Búsquedas registradas | 55 |
| Campañas abiertas | 12 |
| Sectores de mapa creados | 456 |
| Filas en el Google Sheet | 4.712 |
| Requests gastados hoy | 49 de 50 |

La base de datos en uso **es Turso**, no el archivo local: el `.env` tiene
`TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` puestos, y eso manda. El archivo
`data/leads.db` quedó como respaldo histórico y ya no se escribe.

Las 12 campañas son de Bogotá en su mayoría (odontólogos, abogados, gimnasios,
agencias de viaje, restaurantes, hoteles, inmobiliarias, panaderías) más
Medellín y Pasto con odontólogos. Ojo: hay tres campañas de Pasto casi
duplicadas, porque la ciudad se escribió de tres formas distintas
(`Pasto, Colombia`, `pasto`, `Pasto, Nariño`). El identificador de campaña sale
del texto, así que cada variante abre una campaña nueva.

Desplegado en Vercel como proyecto `scrapping-nitro2tech`, servido en
`scrapping.nitro2tech.com`.

> Aviso: el bloque "Lo que quedó pendiente" al inicio de `CONTINUAR.md` está
> desactualizado. Dice que faltan credenciales y que nunca se hizo una búsqueda
> real. Ambas cosas ya ocurrieron hace tiempo.

---

## 3. Cómo se ejecuta

**En tu PC:**

```bash
cd "C:\Nico\Nitro2Tech\Scraping web"
.venv\Scripts\python.exe verificar.py   # chequeo de credenciales, cuesta $0
.venv\Scripts\python.exe run.py         # abre http://127.0.0.1:8000
```

**En producción:** cada `git push` a `main` dispara el despliegue en Vercel. El
proyecto está conectado al repo `nitro2technology-rgb/clientesPotenciales`.
Los pasos completos y el DNS están en `DEPLOY.md`.

Importante: Vercel **no lee el `.env`**. Toda variable nueva que agregues al
`.env` hay que declararla también en Vercel, en *Settings* → *Environment
Variables*, y volver a desplegar. Es el error más fácil de cometer.

---

## 4. Mapa de archivos

```
app/
  main.py            Endpoints FastAPI. Es la puerta de entrada de todo.
  places.py          Cliente de Google Places API + Geocoding. Aquí se gasta.
  campaign.py        Barrido por sectores: qué zona toca ahora, qué ya se vio.
  grid.py            Matemática de la rejilla: partir la ciudad en cuadros.
  classifier.py      La regla de negocio: ¿es lead o no?
  crm.py             Seguimiento: estados, canales y puente con el Sheet.
  social_domains.py  Lista de dominios que cuentan como "no tiene web propia".
  storage.py         SQLite/Turso: histórico, dedupe, campañas, cuota,
                     geocaché y las consultas del seguimiento.
  turso.py           Cliente HTTP de Turso que imita la interfaz de sqlite3.
  sheets.py          Escritura en Google Sheets. Nunca tumba una búsqueda.
  exports.py         Generación de .xlsx y .csv.
  models.py          Modelos Pydantic y normalización de teléfonos.
  config.py          Lectura del .env.
api/index.py         Envoltorio ASGI para Vercel.
static/              Frontend sin frameworks.
  index.html app.js styles.css   El buscador.
  crm.html   crm.js  crm.css     El seguimiento de clientes.
run.py               Lanzador local con banner de estado.
verificar.py         Chequeo de las 3 credenciales sin gastar dinero.
migrar_a_turso.py    Subida del SQLite local a Turso. Idempotente.
```

Documentos que ya existían: `README.md` (guía de uso), `CONTINUAR.md`
(bitácora y decisiones), `DEPLOY.md` (despliegue), `PROYECTO_LEADS_MAPS.md`
(especificación original).

---

## 5. El flujo completo de una búsqueda

Hay **dos modos**, y el que se usa de verdad es el segundo.

### Modo simple, `POST /api/buscar`

1. `places.geocodificar()` convierte la ciudad en coordenadas. Si la ciudad ya
   se buscó antes, sale del geocaché y no cuesta nada.
2. Se llama a Text Search con `locationBias` circular, hasta 3 páginas de 20.
3. Cada resultado se convierte en `Negocio` y pasa por `clasificar()`.
4. Se guarda en la base y se agregan las filas nuevas al Sheet.

Su límite es el de Google: repetir mañana la misma consulta devuelve los mismos
60 resultados. Por eso existe el modo campaña.

### Modo campaña, `POST /api/campana/buscar` — el que importa

1. **Identidad de campaña.** `storage.id_campana()` mezcla ciudad, categoría y
   modo en un hash. Misma pareja, misma campaña.
2. **Primera vez:** se geocodifica la ciudad, `grid.lado_celda_recomendado()`
   elige el tamaño del cuadro y `grid.generar_celdas()` cubre el círculo de
   búsqueda con cuadros, **ordenados de dentro hacia afuera**. Cada cuadro se
   guarda como celda pendiente.
3. **Cada vez que pulsas Buscar:** se toman las siguientes celdas pendientes,
   tantas como diga `CELDAS_POR_SESION`, y se busca dentro de cada una con
   `locationRestriction` rectangular.
4. **Filtro de novedad:** se descarta todo Place ID que ya esté en la base. En
   pantalla solo aparece lo que no tenías.
5. Cada celda explorada se marca con la fecha. Si se acaba la cuota diaria a
   media sesión, la celda en curso **no se marca**, así que mañana se retoma
   justo ahí.
6. Cuando no quedan celdas pendientes, la campaña se declara completa.

Esto es lo que hace que volver a buscar mañana traiga negocios distintos.

---

## 6. Pieza por pieza

### `app/places.py` — donde se gasta el dinero

Es el único módulo que llama a Google. Tres cosas que no hay que romper:

- **Field masking.** Cada llamada manda la cabecera `X-Goog-FieldMask` con solo
  los campos de `CAMPOS_BASE`, más `CAMPOS_RATING` si el usuario pidió
  puntuación. Pedir campos de más sube el SKU y por lo tanto el precio.
- **Contador antes de llamar.** `_gastar_request()` suma el request **antes** de
  hacer la petición, así que los intentos fallidos también cuentan. Es
  deliberado: un 403 en bucle también le cuesta dinero a Google.
- **Rectángulos, no círculos.** En Text Search, `locationRestriction` solo
  acepta rectángulo. El círculo únicamente vale para `locationBias`, que es una
  preferencia blanda y dejaría colarse negocios del centro de la ciudad en cada
  sector. Esto ya se implementó mal una vez.

Precios en pantalla: `PRECIO_BUSQUEDA_BASE` 40, `PRECIO_BUSQUEDA_RATING` 45 y
`PRECIO_GEOCODING` 5 dólares por mil requests. **Son estimaciones escritas a
mano**, no datos que devuelva Google. Si Google cambia tarifas, hay que
editarlas aquí.

### `app/grid.py` — la rejilla

Convierte kilómetros a grados y arma los cuadros. El tamaño de celda sale de
`lado_celda_recomendado()`:

| Radio pedido | Lado de celda |
|---|---|
| hasta 2 km | una sola celda |
| hasta 6 km | 2 km |
| hasta 15 km | 3 km |
| hasta 30 km | 4 km |
| más de 30 km | 6 km |

Celdas muy grandes desperdician resultados, porque cada consulta topa en 60 y el
resto se pierde. Celdas muy chicas disparan el número de requests. Si quieres
barrer más fino una ciudad concreta, este es el lugar.

### `app/classifier.py` y `app/social_domains.py` — la regla de negocio

`clasificar()` son quince líneas y decide todo:

- sin sitio web, es lead, motivo "Sin sitio web";
- sitio web en la lista de redes sociales, es lead, motivo "Sitio web es solo
  red social (...)";
- cualquier otra cosa, no es lead, motivo "Ya tiene sitio web propio".

`LISTA_REDES_SOCIALES` está **activa** con Facebook e Instagram y sus dominios
cortos. `CANDIDATOS_OPCIONALES` es una lista preparada pero apagada: WhatsApp,
Linktree, TikTok, X, YouTube, LinkedIn, Pinterest, Wix, Blogspot, WordPress y
los sitios autogenerados de Google Business. Para activar cualquiera basta
moverlo de una lista a la otra. Los subdominios se detectan solos, así que
`m.facebook.com` ya cuenta sin escribirlo.

Aquí hay una decisión de negocio que quizá quieras revisar: hoy un negocio cuyo
único sitio es `business.site` de Google cuenta como **no lead**, aunque en la
práctica no tenga web propia.

### `app/storage.py` y `app/turso.py` — la memoria

Seis tablas: `negocios`, `busquedas`, `campanas`, `celdas`, `geocache` y
`uso_api`. El mismo SQL sirve para el archivo local y para Turso, porque
`turso.py` implementa a mano lo justo de la interfaz de `sqlite3` que usa el
resto: `execute`, `executemany`, `executescript`, y filas accesibles por índice
y por nombre.

Dos detalles que conviene tener presentes:

- Contra Turso **cada `execute` es un viaje de red** y se autoconfirma. No hay
  transacciones de varias sentencias. Si alguna modificación futura necesita
  atomicidad real, esto no la da.
- `place_ids_existentes()` se trae **todos** los Place ID a memoria para
  deduplicar. Con 3.725 filas va sobrado. Si esto creciera a cientos de miles,
  habría que cambiarlo por consultas puntuales.

La clave primaria de `negocios` es el `place_id`, y las inserciones usan
`INSERT OR IGNORE`. Consecuencia importante: **un negocio ya guardado nunca se
actualiza**. Si cambia su teléfono o abre una web, la base conserva lo viejo.

### `app/sheets.py` — el Google Sheet

Hoja `Leads` del Sheet `1xrpddOYXUIvi84oKFKiEdwfI49wJR65NYDEGqMYIS5I`. Se
escribe con `append_rows` solo para los Place ID que aún no estén en la
columna O.

El módulo **nunca** tumba una búsqueda: cualquier fallo se atrapa y se devuelve
como aviso de texto, con los datos ya guardados en la base. En modo demo se
niega a escribir, para no ensuciar leads reales con datos inventados.

### `app/models.py` — la normalización de teléfonos

`solo_digitos()` es la función que más ruido ha dado. Convierte
`+57 312 721 7006` en `573127217006`. Dos razones: el `+` inicial hacía que
Sheets leyera la celda como fórmula y escribiera `#ERROR!`, y los espacios y
paréntesis estorban para buscar, marcar y cruzar datos.

A los números nacionales de 10 dígitos que empiezan por 3 o por 6 se les
antepone el 57. Cualquier otra longitud se deja tal cual, porque adivinar el
país de un número suelto se equivoca más de lo que acierta.

Se aplica como validador del modelo `Negocio`, así que limpia por igual lo que
llega de Google, lo que sale a Excel y lo que va al Sheet. No hay forma de que
entre un símbolo a la columna de teléfono sin pasar por aquí.

### `app/exports.py` — Excel y CSV

El `.xlsx` sale con encabezado azul, filas verdes para los leads y grises para
los que ya tienen web, autofiltro y anchos de columna fijos. El `.csv` usa punto
y coma como separador y lleva BOM, que es lo que necesita el Excel en español
para respetar las tildes.

### `static/` — el frontend

HTML, CSS y JavaScript planos, sin framework ni compilación. `app.js` hace tres
cosas interesantes:

- **Estima el costo antes de llamar** y lo muestra desglosado en un modal de
  confirmación, con el total en dólares y los requests que se van a gastar. Esa
  estimación es un cálculo del navegador, independiente del backend.
- Lleva una lista de 20 categorías sugeridas que mapean el nombre en español al
  tipo de Places, por ejemplo peluquerías a `hair_salon`.
- Para descargar, **reenvía al backend las filas que ya tiene en pantalla**, en
  vez de pedirlas por identificador. Es necesario en serverless: cada petición
  puede caer en una instancia distinta y no existe una "última búsqueda"
  compartida en memoria.

### `api/index.py` — el envoltorio de Vercel

Vercel reescribe la ruta y la app recibiría `/api/index/lo-que-sea`. Este
envoltorio le devuelve la ruta original antes de pasársela a FastAPI. Si algún
día Vercel dejara de reescribir, el envoltorio no haría nada.

---

## 6bis. El seguimiento de clientes (`/crm`)

Lo que antes se llevaba a mano en el Sheet: a quién llamar, qué se habló y qué
falta por hacer. Misma app, mismo dominio, misma base.

### Los estados

Once, agrupados en tres bloques. El grupo es lo que se usa para filtrar rápido.

| Grupo | Estados |
|---|---|
| Pendientes | Sin contactar · No contestó · Volver a llamar |
| En proceso | Pidió información · Contactado · Info enviada · Interesado |
| Cerrados | Cliente cerrado · Finalizado · No le interesa · Número equivocado |

Todo negocio arranca en **Sin contactar** sin que exista ninguna fila suya: se
resuelve con un LEFT JOIN y un COALESCE. Por eso los 3.738 negocios ya estaban
en la página el primer día, sin migrar nada.

### Los canales

Llamada, WhatsApp, Correo, Visita y **Nota interna**. La nota es la distinta:
no suma intento ni mueve la fecha de último contacto, porque escribir un
recordatorio no es haber llamado.

### La regla que lo sostiene

**Ningún estado cambia sin dejar rastro.** Toda escritura pasa por
`crm.registrar()`, que primero inserta en `interacciones` y después actualiza
`seguimiento`. El botón "No contestó" de la lista y el formulario largo de la
ficha usan exactamente el mismo camino.

### Los filtros

Texto libre (nombre, teléfono o dirección), categoría, ciudad, estado suelto o
grupo entero, contactadas o no, lead o no, y tipo de teléfono: **celular, fijo
o sin teléfono**. El celular importa porque es el único al que se le puede
escribir por WhatsApp.

Además hay una **agenda**: los clientes cuyo "volver a contactar el" ya venció
o es hoy.

### Teléfonos

Las primeras campañas guardaron los números sin normalizar. En la base conviven
`573127217006` y `312 7217006`, y 2.599 de los 3.162 son del formato viejo. El
seguimiento los limpia **al leerlos**, sin reescribir el histórico:

- en pantalla y en los enlaces, `models.solo_digitos()` los deja en dígitos;
- en los filtros, el SQL limpia la columna al vuelo con REPLACE anidados.

Sin esto el enlace de WhatsApp llevaría un espacio dentro y no abriría, y el
filtro de celular dejaría fuera a cuatro de cada cinco.

### Dos tablas nuevas

`seguimiento`, una fila por cliente tocado (estado, responsable, próximo paso,
último contacto, intentos, último comentario), e `interacciones`, una fila por
llamada, WhatsApp, correo o nota, que nunca se edita ni se borra.

Se crean solas con CREATE TABLE IF NOT EXISTS, como las demás. No tocan la
tabla `negocios`: sus inserciones usan una tupla posicional de 17 valores y
añadir una columna ahí la rompería.

### Puente con el Google Sheet

El reparto de columnas, y el motivo de cada una:

| Col | Qué lleva | Quién escribe |
|---|---|---|
| N | Estado de contacto | el seguimiento |
| P | Comentario | **tú, a mano.** El código solo la lee |
| Q | Último comentario del seguimiento | el seguimiento |

El comentario va a la **Q y no a la P** justamente para no pisar las notas que
ya tenías escritas a mano. Son dos columnas distintas a propósito.

**Cada vez que guardas, el estado y el comentario viajan solos al Sheet.** El
orden importa: primero se escribe en la base de datos y después en el Sheet,
así que si el Sheet está caído solo se pierde el reflejo, nunca el seguimiento.
En ese caso la página lo dice con un aviso amarillo. Se puede apagar con
`CRM_SYNC_SHEET=false`, y entonces guardar es instantáneo y el Sheet se pone al
día solo con el botón.

La hoja nació con 16 columnas, hasta la P. La primera escritura la ensancha
hasta la Q sola; sin eso Google devuelve "Range exceeds grid limits".

Además hay dos botones:

- **Importar del Sheet** lee la columna N (el estado escrito a mano) y la P (el
  comentario), y rellena a quien todavía no tiene seguimiento. Nunca pisa lo
  que ya escribiste en la página, así que se puede repetir sin miedo. Si no
  reconoce la frase de la columna N, deja el cliente en "Contactado" y conserva
  el texto original en el comentario: equivocarse hacia "ya le hablamos" es más
  seguro que hacia "sin contactar", que haría volver a llamar a alguien.
- **Volcar al Sheet** repasa todo el seguimiento de golpe y deja al día las
  columnas N y Q. Sirve para ponerse al corriente.

### La clave

`CRM_PASSWORD` en el `.env`. Vacía, la página queda abierta igual que el
buscador. Puesta, el navegador guarda una cookie firmada durante 30 días. No
hay sesiones en memoria a propósito: en serverless cada petición cae en una
instancia distinta y caducarían solas.

> Hoy está **vacía**, así que cualquiera que acierte la URL ve los teléfonos de
> los negocios y los comentarios de las llamadas. Ponla en el `.env` **y en
> Vercel**.

---

## 7. Los datos

### Tabla `negocios`

`place_id` (clave), `nombre`, `direccion`, `telefono`, `sitio_web`,
`categoria_google`, `rating`, `resenas`, `maps_url`, `email`,
`estado_contacto`, `es_lead`, `motivo`, `fecha_busqueda`, `ciudad_buscada`,
`categoria_buscada`, `busqueda_id`.

### Columnas del Google Sheet

El código escribe **15 columnas, de la A a la O**, en este orden:

| Col | Nombre | Origen |
|---|---|---|
| A | Fecha de busqueda | momento de la consulta |
| B | Ciudad | lo que escribiste |
| C | Categoria buscada | lo que escribiste |
| D | Nombre del negocio | Google |
| E | Direccion | Google |
| F | Telefono | Google, ya normalizado a dígitos |
| G | Sitio web | Google |
| H | Es lead | Si / No |
| I | Motivo | la regla que lo decidió |
| J | Rating | Google, opcional |
| K | Resenas | Google, opcional |
| L | Link Google Maps | Google |
| M | Email | siempre vacío, ver abajo |
| N | Estado de contacto | para llenar a mano |
| O | Place ID | clave de deduplicación |

**La columna P, "Comentario", es tuya.** Se llena a mano en el Sheet y el código
no la toca nunca. Es la primera columna después de las quince, así que si
`_fila()` volviera a devolver dieciséis valores, el decimosexto caería justo
encima de tus comentarios. Ya pasó una vez, en septiembre de 2026, y se
arregló.

La **columna Q, "Ultimo comentario (seguimiento)"**, sí la escribe el código:
es donde la página de seguimiento deja el último comentario de cada cliente.
Se eligió la Q precisamente para dejar la P en paz.

La columna **Email va siempre vacía a propósito**: Google Places no expone
correos. Sacarlos exigiría visitar la web de cada negocio, y eso solo aplica a
los que sí tienen web, que son justo los que no son leads.

---

## 8. La API HTTP

| Método y ruta | Para qué |
|---|---|
| `GET /api/estado` | Configuración y consumo del día. Lo usa el frontend para pintar avisos. Gratis. |
| `POST /api/buscar` | Búsqueda simple. Parámetros `incluir_rating` y `guardar`. |
| `POST /api/campana/buscar` | Siguiente lote de sectores. Parámetros `incluir_rating`, `max_celdas`, `guardar`. |
| `GET /api/campana/estado` | Progreso de una campaña por ciudad, categoría y modo. No gasta. |
| `GET /api/campanas` | Lista de todas las campañas con su progreso. |
| `POST /api/campana/reiniciar` | Marca todos los sectores como pendientes otra vez. |
| `GET /api/historico` | Negocios guardados, con `limite` y `solo_leads`. |
| `GET /api/descargar/xlsx` y `/csv` | Descarga desde la base: una búsqueda o el histórico. |
| `POST /api/descargar/xlsx` y `/csv` | Descarga a partir de las filas que manda el navegador. |
| `GET /` | El buscador. |
| `GET /crm` | La página de seguimiento. |
| `GET /api/crm/opciones` | Estados, canales, categorías, ciudades y contadores. |
| `GET /api/crm/clientes` | Lista filtrada y paginada. |
| `GET /api/crm/cliente/{place_id}` | Ficha con su historial completo. |
| `POST /api/crm/cliente/{place_id}/interaccion` | Anota la llamada y fija el estado. Único camino de escritura. |
| `GET /api/crm/descargar/xlsx` y `/csv` | Excel o CSV de lo que se ve con los filtros puestos. |
| `POST /api/crm/sheet/importar` y `/sincronizar` | Los dos puentes con el Sheet. |
| `GET /api/crm/sesion`, `POST /api/crm/login` y `/logout` | La clave, si está puesta. |

Códigos de error propios: **429** cuando se acabó la cuota diaria, **502**
cuando Google responde mal, **503** cuando Turso no contesta. El 503 es
deliberado: sin base de datos no hay deduplicación ni contador de cuota, y es
mejor parar que seguir gastando a ciegas.

---

## 9. Control de costos

Cuatro frenos, de más débil a más fuerte:

1. **La estimación en pantalla**, antes de confirmar.
2. **`MAX_PAGES_PER_SEARCH`**, hoy 3. Cada página es un request y trae hasta 20
   negocios.
3. **`CELDAS_POR_SESION`**, hoy 5. Cada sector cuesta hasta 3 requests, así que
   una sesión son como mucho unos 15.
4. **`MAX_REQUESTS_PER_DAY`**, hoy 50. Es un tope duro: al llegar, la app se
   bloquea sola y devuelve 429.

Dos avisos honestos. El contador vive en la base, así que si la base se pierde,
el freno se reinicia. Y el techo de verdad no está en esta app sino en Google
Cloud: la **alerta de presupuesto** y la **cuota diaria de la Places API**.
Conviene confirmar que ambas están puestas.

El geocoding se paga una sola vez por ciudad: después sale del geocaché. Hoy
hay 5 ciudades cacheadas.

---

## 10. Variables del `.env`

| Variable | Hoy | Qué hace |
|---|---|---|
| `GOOGLE_MAPS_API_KEY` | puesta | Places API (New) y Geocoding |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | ruta local | Credenciales de Sheets en tu PC |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | usada en Vercel | El mismo JSON, pegado entero |
| `GOOGLE_SHEET_ID` | puesta | El código largo de la URL del Sheet |
| `GOOGLE_SHEET_TAB` | `Leads` | Pestaña dentro del Sheet |
| `TURSO_DATABASE_URL` | puesta | Si está, la base es Turso y no el archivo |
| `TURSO_AUTH_TOKEN` | puesta | Token de Turso, caduca y se regenera |
| `MAX_REQUESTS_PER_DAY` | 50 | Tope duro diario |
| `MAX_PAGES_PER_SEARCH` | 3 | Páginas por consulta |
| `CELDAS_POR_SESION` | 5 | Sectores por clic en Buscar |
| `CONFIRMAR_ANTES_DE_GASTAR` | true | Modal de confirmación |
| `DEMO_MODE` | false | true = datos inventados, cero llamadas, cero costo |
| `CRM_PASSWORD` | **vacía** | Clave de `/crm`. Vacía = página abierta |
| `CRM_SYNC_SHEET` | true | Reflejar cada seguimiento en el Sheet al guardarlo |
| `HOST` y `PORT` | 127.0.0.1:8000 | Solo para local |

`config.py` limpia comillas y espacios sobrantes al leer, porque es fácil pegar
una ruta entre comillas y que la credencial falle con un error confuso.

---

## 11. Reglas que ya se decidieron

No hace falta volver a discutirlas, y romperlas rompe algo.

1. **Nunca se hace scraping del HTML de Google Maps.** Viola los términos de
   servicio y puede bloquear la cuenta. Todo sale de la API oficial.
2. **El límite de 60 resultados por consulta es de Google.** Tres páginas de
   veinte, y repetir la consulta devuelve lo mismo. La única salida es
   preguntar por otra zona del mapa, que es justo lo que hace la rejilla.
3. **Sectores rectangulares, no circulares**, por lo explicado arriba.
4. **Los teléfonos se guardan como dígitos pelados con indicativo.**
5. **El código nunca escribe en la columna P del Sheet.** Escribe de la A a la
   O con los datos del negocio, y la Q con el último comentario del
   seguimiento. La P es tuya y solo se lee.
6. **El fallo de Sheets nunca tumba una búsqueda.** Se avisa por texto y los
   datos quedan en la base.
7. **En modo demo no se escribe en el Sheet real.**

---

## 12. Dónde tocar para las modificaciones más probables

| Lo que quieras cambiar | Dónde |
|---|---|
| Que WhatsApp, TikTok o Linktree cuenten como lead | Mover el dominio de `CANDIDATOS_OPCIONALES` a `LISTA_REDES_SOCIALES` en `app/social_domains.py` |
| Cambiar la regla de qué es lead | `app/classifier.py`, función `clasificar()` |
| Agregar una columna al Sheet | `ENCABEZADOS` y `_fila()` en `app/sheets.py`, y `_filas()` y `ANCHOS` en `app/exports.py`. Ojo con la columna P |
| Agregar un campo nuevo traído de Google | `CAMPOS_BASE` en `app/places.py`, `_a_negocio()`, el modelo `Negocio`, el esquema de `storage.py` y la fila de Sheets. Sube el precio si el campo es de otro SKU |
| Barrer más fino o más grueso | `lado_celda_recomendado()` en `app/grid.py` |
| Subir o bajar el gasto permitido | Las variables del `.env`, y en Vercel también |
| Actualizar los precios mostrados | Las tres constantes `PRECIO_*` en `app/places.py` |
| Cambiar categorías sugeridas del formulario | La lista `CATEGORIAS` al inicio de `static/app.js` |
| Cambiar el aspecto de la interfaz | `static/index.html` y `static/styles.css` |
| Sacar emails de los negocios | No existe. Habría que escribir un módulo nuevo que visite cada web. Es el cambio más grande de esta lista |
| Agregar o quitar un estado del seguimiento | `ESTADOS` en `app/crm.py`. La página los pide por API, así que se adapta sola |
| Agregar un canal de contacto | `CANALES` en `app/crm.py` |
| Cambiar el mensaje con el que se abre WhatsApp | `PLANTILLA_WHATSAPP` al inicio de `static/crm.js` |
| Entender mejor lo escrito a mano en el Sheet | `_TEXTO_A_ESTADO` en `app/crm.py`. **El orden importa**: gana la primera frase que aparezca |
| Que el comentario deje de viajar al Sheet al guardar | `CRM_SYNC_SHEET=false` en el `.env`, y en Vercel también |
| Cambiar a qué columna del Sheet va el comentario | `COLUMNA_COMENTARIO_CRM` en `app/sheets.py`. Ojo: la P es del usuario |
| Poner o quitar la clave de `/crm` | `CRM_PASSWORD` en el `.env`, y en Vercel también |
| Actualizar negocios ya guardados | Hoy imposible por diseño, por el `INSERT OR IGNORE`. Habría que cambiarlo por un upsert en `storage.guardar_negocios()` |

---

## 13. Cómo probar sin gastar

```bash
.venv\Scripts\python.exe verificar.py                    # las 3 credenciales
.venv\Scripts\python.exe migrar_a_turso.py --verificar   # compara local y nube
```

Y para probar la interfaz entera sin llamar a Google, `DEMO_MODE=true` en el
`.env`. El modo demo inventa negocios con Place ID deterministas, así que la
deduplicación se comporta igual que con datos reales.

La API de Sheets **no cobra**, así que leer o escribir en el Sheet es gratis. Lo
que cuesta es únicamente Places y Geocoding.

---

## 14. Lo que hoy no está resuelto

- **Emails:** la columna existe pero siempre vacía. Google no los da.
- **Campañas duplicadas por el nombre de la ciudad.** `Pasto`, `Pasto, Colombia`
  y `Pasto, Nariño` abren tres campañas distintas y se pisan trabajo. Se
  arreglaría normalizando la ciudad antes de calcular el identificador, pero
  eso cambiaría los identificadores ya existentes.
- **Los negocios guardados no se refrescan nunca.**
- **`/crm` está abierta** mientras `CRM_PASSWORD` siga vacía. Son teléfonos
  de terceros y notas de llamadas.
- **Los teléfonos viejos siguen sin normalizar en la base** y en la columna F
  del Sheet. El seguimiento los limpia al leerlos, así que no estorban, pero
  una normalización de una sola pasada dejaría la base coherente.
- **El seguimiento no tiene transacciones.** Contra Turso cada sentencia
  viaja sola. Se escribe primero la bitácora y después el resumen, así que
  el peor caso es una interacción registrada sin resumen, nunca al revés.
- **Los precios en pantalla son estimaciones escritas a mano.**
- **La cuota diaria depende de la base.** Si Turso se cae, la app devuelve 503 y
  no gasta, que es el comportamiento correcto, pero tampoco funciona.
- **Falta confirmar en Google Cloud** que estén puestas la alerta de presupuesto
  y la cuota diaria de la Places API. Es la única protección real contra un
  gasto inesperado.
