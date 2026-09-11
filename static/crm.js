/* Seguimiento de clientes.
 *
 * Todo lo que se ve aqui sale de /api/crm. La pagina no guarda nada por su
 * cuenta: cada cambio se manda al servidor y se vuelve a leer, para que dos
 * pestanas abiertas nunca muestren cosas distintas.
 */

// Mensaje con el que se abre WhatsApp. Se le pega el nombre del negocio.
// Cambia este texto y cambia en toda la pagina.
const PLANTILLA_WHATSAPP =
  "Hola, buen dia. Le escribo de Nitro2Tech. Vi que {negocio} no tiene pagina " +
  "web propia y queria contarle como podemos hacerle una. Le comparto la " +
  "informacion?";

const TONO_POR_ESTADO = {};   // se llena al cargar las opciones
const ETIQUETA_ESTADO = {};
const ETIQUETA_CANAL = {};

const estado = {
  opciones: null,
  pagina: 1,
  paginas: 1,
  total: 0,
  clientes: [],
  abierto: null,        // place_id de la ficha abierta
  canal: "llamada",
  peticion: 0,          // descarta respuestas que llegan fuera de orden
};

const CLAVE_RESPONSABLE = "crm_responsable";

const $ = (id) => document.getElementById(id);

/** Quien esta llamando hoy. Se recuerda en este navegador, no en la base:
 *  es una comodidad por persona, no un dato compartido del cliente. */
function responsableRecordado() {
  try { return localStorage.getItem(CLAVE_RESPONSABLE) || ""; } catch (_) { return ""; }
}
function recordarResponsable(nombre) {
  try {
    if (nombre.trim()) localStorage.setItem(CLAVE_RESPONSABLE, nombre.trim());
  } catch (_) { /* navegacion privada: seguimos sin recordar */ }
}
const esc = (texto) =>
  String(texto ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

// ---------------------------------------------------------------- red
async function api(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, {
    headers: { "Content-Type": "application/json" },
    ...opciones,
  });
  if (respuesta.status === 401) {
    mostrarClave();
    throw new Error("sesion");
  }
  if (!respuesta.ok) {
    let detalle = `Error ${respuesta.status}`;
    try {
      const cuerpo = await respuesta.json();
      if (cuerpo.detail) detalle = cuerpo.detail;
    } catch (_) { /* respuesta sin JSON: nos quedamos con el codigo */ }
    throw new Error(detalle);
  }
  return respuesta.json();
}

function aviso(texto, tipo = "info") {
  const caja = $("mensaje");
  if (!texto) { caja.classList.add("oculto"); return; }
  caja.className = tipo;
  caja.textContent = texto;
  caja.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ------------------------------------------------------------- la clave
function mostrarClave() {
  $("pantalla-clave").classList.remove("oculto");
  $("app").classList.add("oculto");
  $("clave").focus();
}

$("form-clave").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const error = $("clave-error");
  try {
    const respuesta = await fetch("/api/crm/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clave: $("clave").value }),
    });
    if (!respuesta.ok) {
      error.textContent = "Clave incorrecta.";
      error.classList.remove("oculto");
      return;
    }
    error.classList.add("oculto");
    $("pantalla-clave").classList.add("oculto");
    $("clave").value = "";
    await arrancar();
  } catch (_) {
    error.textContent = "No se pudo verificar la clave. Reintenta.";
    error.classList.remove("oculto");
  }
});

$("btn-salir").addEventListener("click", async () => {
  await fetch("/api/crm/logout", { method: "POST" });
  location.reload();
});

// --------------------------------------------------------------- filtros
function leerFiltros() {
  const valorEstado = $("f-estado").value;
  const parametros = new URLSearchParams();

  const texto = $("f-texto").value.trim();
  if (texto) parametros.set("texto", texto);
  if ($("f-categoria").value) parametros.set("categoria", $("f-categoria").value);
  if ($("f-ciudad").value) parametros.set("ciudad", $("f-ciudad").value);
  if ($("f-contactado").value) parametros.set("contactado", $("f-contactado").value);
  if ($("f-lead").value) parametros.set("es_lead", $("f-lead").value);
  if ($("f-telefono").value) parametros.set("telefono", $("f-telefono").value);
  if ($("f-agenda").checked) parametros.set("agenda", "true");
  parametros.set("orden", $("f-orden").value || "relevancia");

  // El desplegable mezcla estados sueltos y grupos enteros ("grupo:pendiente"),
  // porque casi siempre se quiere filtrar por "lo que esta pendiente", no por
  // un estado concreto. El backend solo entiende estados sueltos.
  if (valorEstado.startsWith("grupo:")) {
    const grupo = valorEstado.slice(6);
    (estado.opciones.grupos[grupo] || []).forEach((e) => parametros.append("estados", e));
  } else if (valorEstado) {
    parametros.append("estados", valorEstado);
  }
  return parametros;
}

function aplicarFiltros() {
  estado.pagina = 1;
  cargarClientes();
}

// Al escribir no se llama en cada tecla: se espera a que la persona pare.
let temporizador = null;
$("f-texto").addEventListener("input", () => {
  clearTimeout(temporizador);
  temporizador = setTimeout(aplicarFiltros, 350);
});

["f-categoria", "f-ciudad", "f-estado", "f-contactado", "f-lead", "f-telefono",
 "f-orden", "f-agenda"].forEach((id) => {
  $(id).addEventListener("change", aplicarFiltros);
});

function limpiarFiltros() {
  ["f-texto", "f-categoria", "f-ciudad", "f-estado", "f-contactado", "f-lead",
   "f-telefono"].forEach((id) => { $(id).value = ""; });
  $("f-agenda").checked = false;
  $("f-orden").value = "relevancia";
}

$("btn-limpiar").addEventListener("click", () => {
  limpiarFiltros();
  aplicarFiltros();
});

$("btn-antes").addEventListener("click", () => {
  if (estado.pagina > 1) { estado.pagina -= 1; cargarClientes(); }
});
$("btn-despues").addEventListener("click", () => {
  if (estado.pagina < estado.paginas) { estado.pagina += 1; cargarClientes(); }
});

$("btn-xlsx").addEventListener("click", () => descargar("xlsx"));
$("btn-csv").addEventListener("click", () => descargar("csv"));

function descargar(formato) {
  const parametros = leerFiltros();
  window.open(`/api/crm/descargar/${formato}?${parametros.toString()}`, "_blank");
}

// --------------------------------------------------------------- opciones
function pintarOpciones(opciones) {
  estado.opciones = opciones;

  opciones.estados.forEach((e) => {
    TONO_POR_ESTADO[e.clave] = e.tono;
    ETIQUETA_ESTADO[e.clave] = e.etiqueta;
  });
  opciones.canales.forEach((c) => { ETIQUETA_CANAL[c.clave] = c.etiqueta; });

  rellenar($("f-categoria"), opciones.categorias, "Todas");
  rellenar($("f-ciudad"), opciones.ciudades, "Todas");
  rellenar($("responsables"), opciones.responsables, null);

  $("f-orden").innerHTML = opciones.ordenes
    .map((o) => `<option value="${esc(o.clave)}">${esc(o.etiqueta)}</option>`)
    .join("");

  const nombreGrupo = {
    pendiente: "Pendientes",
    proceso: "En proceso",
    cerrado: "Cerrados",
  };
  let html = '<option value="">Todos los estados</option>';
  for (const [grupo, titulo] of Object.entries(nombreGrupo)) {
    html += `<option value="grupo:${grupo}">${titulo} (todos)</option>`;
    html += `<optgroup label="${titulo}">`;
    html += opciones.estados
      .filter((e) => e.grupo === grupo)
      .map((e) => `<option value="${esc(e.clave)}">${esc(e.etiqueta)}</option>`)
      .join("");
    html += "</optgroup>";
  }
  $("f-estado").innerHTML = html;

  // El mismo desplegable, sin grupos, para la ficha.
  $("s-estado").innerHTML = Object.entries(nombreGrupo).map(([grupo, titulo]) =>
    `<optgroup label="${titulo}">` + opciones.estados
      .filter((e) => e.grupo === grupo)
      .map((e) => `<option value="${esc(e.clave)}">${esc(e.etiqueta)}</option>`)
      .join("") + "</optgroup>"
  ).join("");

  $("canales").innerHTML = opciones.canales
    .map((c) => `<button type="button" class="canal" data-canal="${esc(c.clave)}">${esc(c.etiqueta)}</button>`)
    .join("");
  $("canales").querySelectorAll(".canal").forEach((boton) => {
    boton.addEventListener("click", () => elegirCanal(boton.dataset.canal));
  });
  elegirCanal("llamada");

  pintarResumen(opciones);
}

function rellenar(elemento, valores, etiquetaVacia) {
  const opciones = valores.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`);
  if (etiquetaVacia !== null) opciones.unshift(`<option value="">${etiquetaVacia}</option>`);
  elemento.innerHTML = opciones.join("");
}

function pintarResumen(opciones) {
  const suma = (claves) => claves.reduce((t, c) => t + (opciones.resumen[c] || 0), 0);
  const enProceso = suma([
    ...opciones.grupos.pendiente.filter((e) => e !== "sin_contactar"),
    ...opciones.grupos.proceso,
  ]);

  const tarjetas = [
    { valor: opciones.total, etiqueta: "Negocios en la base", filtro: "todo" },
    { valor: opciones.resumen.sin_contactar || 0, etiqueta: "Sin contactar", tono: "", filtro: "sin" },
    { valor: enProceso, etiqueta: "En conversación", tono: "azul", filtro: "proceso" },
    { valor: opciones.agenda_hoy, etiqueta: "Para llamar hoy", tono: "ambar", filtro: "agenda" },
    { valor: suma(opciones.grupos.cerrado), etiqueta: "Cerrados", tono: "verde", filtro: "cerrado" },
  ];

  $("resumen").innerHTML = tarjetas.map((t) => `
    <button type="button" class="stat pulsable" data-filtro="${t.filtro}">
      <div class="valor ${t.tono || ""}">${t.valor.toLocaleString("es-CO")}</div>
      <div class="etiqueta">${t.etiqueta}</div>
    </button>`).join("");

  $("resumen").querySelectorAll(".stat").forEach((boton) => {
    boton.addEventListener("click", () => atajo(boton.dataset.filtro));
  });
}

/** Las tarjetas de arriba son atajos a los filtros de abajo. */
function atajo(cual) {
  limpiarFiltros();
  if (cual === "sin") $("f-contactado").value = "no";
  if (cual === "proceso") $("f-estado").value = "grupo:proceso";
  if (cual === "cerrado") $("f-estado").value = "grupo:cerrado";
  if (cual === "agenda") $("f-agenda").checked = true;
  aplicarFiltros();
}

// --------------------------------------------------------------- la lista
async function cargarClientes() {
  const miPeticion = ++estado.peticion;
  $("tabla").classList.add("cargando-tabla");
  try {
    const datos = await api(`/api/crm/clientes?${leerFiltros().toString()}`);
    if (miPeticion !== estado.peticion) return;   // llego tarde: ya hay otra
    estado.clientes = datos.clientes;
    estado.total = datos.total;
    estado.paginas = datos.paginas;
    estado.pagina = datos.pagina;
    pintarTabla();
    aviso("");
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  } finally {
    if (miPeticion === estado.peticion) {
      $("tabla").classList.remove("cargando-tabla");
    }
  }
}

function pintarTabla() {
  const cuerpo = $("tabla").querySelector("tbody");
  cuerpo.innerHTML = estado.clientes.map(fila).join("");
  $("vacio").classList.toggle("oculto", estado.clientes.length > 0);

  $("conteo").innerHTML = estado.total
    ? `${estado.total.toLocaleString("es-CO")} clientes <em>con estos filtros</em>`
    : "";
  $("pagina-texto").textContent = `Página ${estado.pagina} de ${estado.paginas}`;
  $("btn-antes").disabled = estado.pagina <= 1;
  $("btn-despues").disabled = estado.pagina >= estado.paginas;

  cuerpo.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", (evento) => {
      // Los enlaces y botones de la fila hacen lo suyo sin abrir la ficha.
      if (evento.target.closest("a, button")) return;
      abrirFicha(tr.dataset.id);
    });
  });
  cuerpo.querySelectorAll("[data-fallo]").forEach((boton) => {
    boton.addEventListener("click", () => marcarSinRespuesta(boton.dataset.fallo));
  });
}

function fila(cliente) {
  const tono = TONO_POR_ESTADO[cliente.estado] || "gris";
  const proximo = cliente.proximo_paso
    ? `<span class="${cliente.vencido ? "fecha-vencida" : ""}">${esc(cliente.proximo_paso)}</span>`
    : '<span class="sin-dato">—</span>';

  const telefono = cliente.telefono
    ? `<span class="tel">${esc(cliente.telefono)}
         <span class="tel-tipo">${cliente.es_celular ? "Celular" : "Fijo"}</span></span>`
    : '<span class="sin-dato">Sin teléfono</span>';

  const acciones = [];
  if (cliente.telefono) {
    acciones.push(`<a class="mini llamar" href="${esc(cliente.telefono_url)}">Llamar</a>`);
  }
  if (cliente.whatsapp_url) {
    acciones.push(`<a class="mini wa" href="${enlaceWhatsapp(cliente)}" target="_blank" rel="noopener">WhatsApp</a>`);
  }
  if (cliente.telefono) {
    acciones.push(`<button type="button" class="mini fallo" data-fallo="${esc(cliente.place_id)}">No contestó</button>`);
  }

  return `
    <tr data-id="${esc(cliente.place_id)}">
      <td class="celda-negocio">
        <div class="nombre">${esc(cliente.nombre)}</div>
        <div class="sub">${esc(cliente.categoria_buscada)} · ${esc(cliente.ciudad_buscada)}</div>
      </td>
      <td>${telefono}</td>
      <td><span class="badge ${tono}">${esc(cliente.estado_etiqueta)}</span>
          ${cliente.intentos ? `<div class="sub">${cliente.intentos} intento(s)</div>` : ""}</td>
      <td>${cliente.ultimo_contacto ? esc(cliente.ultimo_contacto.slice(0, 10)) : '<span class="sin-dato">—</span>'}</td>
      <td>${proximo}</td>
      <td class="celda-comentario">${esc(cliente.comentario) || '<span class="sin-dato">—</span>'}</td>
      <td><div class="acciones-fila">${acciones.join("")}</div></td>
    </tr>`;
}

function enlaceWhatsapp(cliente) {
  const texto = PLANTILLA_WHATSAPP.replace("{negocio}", cliente.nombre || "su negocio");
  return `${cliente.whatsapp_url}?text=${encodeURIComponent(texto)}`;
}

/** El caso mas repetido de todos: llamaste y no te contestaron. Un clic. */
async function marcarSinRespuesta(placeId) {
  try {
    const datos = await api(`/api/crm/cliente/${encodeURIComponent(placeId)}/interaccion`, {
      method: "POST",
      body: JSON.stringify({
        estado: "no_contesta",
        canal: "llamada",
        comentario: "",
        proximo_paso: "",
        responsable: responsableRecordado(),
      }),
    });
    await refrescar();
    if (datos.aviso) aviso(datos.aviso, "aviso");
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  }
}

// ---------------------------------------------------------------- ficha
async function abrirFicha(placeId) {
  try {
    const datos = await api(`/api/crm/cliente/${encodeURIComponent(placeId)}`);
    estado.abierto = placeId;
    pintarFicha(datos);
    $("ficha").classList.remove("oculto");
    $("ficha-fondo").classList.remove("oculto");
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  }
}

function cerrarFicha() {
  estado.abierto = null;
  $("ficha").classList.add("oculto");
  $("ficha-fondo").classList.add("oculto");
}

$("ficha-cerrar").addEventListener("click", cerrarFicha);
$("ficha-fondo").addEventListener("click", cerrarFicha);
document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && estado.abierto) cerrarFicha();
});

function pintarFicha(datos) {
  const c = datos.cliente;
  $("ficha-nombre").textContent = c.nombre;
  $("ficha-sub").textContent =
    `${c.categoria_buscada || ""} · ${c.ciudad_buscada || ""}`.replace(/^ · | · $/, "");

  if (c.telefono) {
    const botones = [`<a class="mini llamar" href="${esc(c.telefono_url)}">Llamar</a>`];
    if (c.whatsapp_url) {
      botones.push(`<a class="mini wa" href="${enlaceWhatsapp(c)}" target="_blank" rel="noopener">WhatsApp</a>`);
    }
    $("ficha-telefono").innerHTML = `
      <div>
        <div class="numero">${esc(c.telefono)}</div>
        <div class="sub">${c.es_celular ? "Celular · sirve WhatsApp" : "Línea fija"}</div>
      </div>
      <div class="acciones-fila">${botones.join("")}</div>`;
  } else {
    $("ficha-telefono").innerHTML =
      '<div class="sub">Este negocio no tiene teléfono en su ficha de Google Maps.</div>';
  }

  const sitio = c.sitio_web
    ? `<a href="${esc(c.sitio_web)}" target="_blank" rel="noopener">${esc(c.sitio_web)}</a>`
    : '<span class="sin-dato">Ninguno</span>';
  const maps = c.maps_url
    ? `<a href="${esc(c.maps_url)}" target="_blank" rel="noopener">Ver en Maps</a>`
    : '<span class="sin-dato">—</span>';

  $("ficha-datos").innerHTML = `
      <dt>Dirección</dt><dd>${esc(c.direccion) || "—"}</dd>
      <dt>Sitio web</dt><dd>${sitio}</dd>
      <dt>Clasificación</dt><dd>${c.es_lead ? "Lead" : "Ya tiene web propia"} · ${esc(c.motivo)}</dd>
      <dt>Valoración</dt><dd>${c.rating ? `${c.rating} (${c.resenas || 0} reseñas)` : "Sin datos"}</dd>
      <dt>Maps</dt><dd>${maps}</dd>
      <dt>Intentos</dt><dd>${c.intentos || 0}${c.ultimo_contacto ? ` · último el ${esc(c.ultimo_contacto.slice(0, 10))}` : ""}</dd>`;

  // Si el cliente sigue "sin contactar" pero estas abriendo la ficha para
  // anotar algo, es que ya le hablaste: se propone "Contactado" para que
  // nadie guarde una llamada dejando el estado en sin contactar.
  $("s-estado").value = c.estado === "sin_contactar" ? "contactado" : c.estado;
  $("s-comentario").value = "";
  $("s-proximo").value = c.proximo_paso || "";
  $("s-responsable").value = c.responsable || responsableRecordado();
  elegirCanal(c.estado === "sin_contactar" ? "llamada" : (c.ultimo_canal || "llamada"));

  pintarHistorial(datos.interacciones);
}

function pintarHistorial(interacciones) {
  $("historial-vacio").classList.toggle("oculto", interacciones.length > 0);
  $("historial").innerHTML = interacciones.map((i) => `
    <li>
      <div class="cuando">${esc(i.fecha)}${i.autor ? ` · ${esc(i.autor)}` : ""}</div>
      <div class="que">
        <b>${esc(ETIQUETA_CANAL[i.canal] || i.canal)}</b>
        → ${esc(ETIQUETA_ESTADO[i.estado_nuevo] || i.estado_nuevo)}
        ${i.proximo_paso ? ` · volver el ${esc(i.proximo_paso)}` : ""}
      </div>
      ${i.comentario ? `<div class="comentario">${esc(i.comentario)}</div>` : ""}
    </li>`).join("");
}

function elegirCanal(clave) {
  estado.canal = clave;
  $("canales").querySelectorAll(".canal").forEach((boton) => {
    boton.classList.toggle("activo", boton.dataset.canal === clave);
  });
}

$("form-seguimiento").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (!estado.abierto) return;
  const boton = evento.target.querySelector("button[type=submit]");
  boton.disabled = true;
  recordarResponsable($("s-responsable").value);
  try {
    const datos = await api(
      `/api/crm/cliente/${encodeURIComponent(estado.abierto)}/interaccion`,
      {
        method: "POST",
        body: JSON.stringify({
          estado: $("s-estado").value,
          canal: estado.canal,
          comentario: $("s-comentario").value,
          proximo_paso: $("s-proximo").value,
          responsable: $("s-responsable").value,
        }),
      }
    );
    pintarFicha(datos);
    await refrescar();
    // El backend avisa si el Sheet no acepto el reflejo. El dato ya esta
    // guardado igual, asi que es un aviso, nunca un error.
    aviso(datos.aviso || "Seguimiento guardado.", datos.aviso ? "aviso" : "info");
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  } finally {
    boton.disabled = false;
  }
});

/** Vuelve a leer los contadores y la pagina actual tras cualquier cambio. */
async function refrescar() {
  const opciones = await api("/api/crm/opciones");
  pintarResumen(opciones);
  estado.opciones.resumen = opciones.resumen;
  estado.opciones.agenda_hoy = opciones.agenda_hoy;
  await cargarClientes();
}

// ------------------------------------------------------ puente con el Sheet
$("btn-importar").addEventListener("click", async (evento) => {
  evento.target.disabled = true;
  try {
    const datos = await api("/api/crm/sheet/importar", { method: "POST" });
    aviso(datos.aviso, datos.importados ? "info" : "aviso");
    await refrescar();
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  } finally {
    evento.target.disabled = false;
  }
});

$("btn-sincronizar").addEventListener("click", async (evento) => {
  evento.target.disabled = true;
  try {
    const datos = await api("/api/crm/sheet/sincronizar", { method: "POST" });
    aviso(datos.aviso, "info");
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  } finally {
    evento.target.disabled = false;
  }
});

// --------------------------------------------------------------- arranque
async function arrancar() {
  $("app").classList.remove("oculto");
  try {
    pintarOpciones(await api("/api/crm/opciones"));
    await cargarClientes();
  } catch (error) {
    if (error.message !== "sesion") aviso(error.message, "error");
  }
  try {
    const general = await (await fetch("/api/estado")).json();
    if (general.sheet_url) {
      $("link-sheet").href = general.sheet_url;
      $("link-sheet").classList.remove("oculto");
    }
  } catch (_) { /* el enlace al Sheet es un adorno: si falla, da igual */ }
}

(async function inicio() {
  try {
    const sesion = await (await fetch("/api/crm/sesion")).json();
    if (sesion.protegido) $("btn-salir").classList.remove("oculto");
    if (sesion.protegido && !sesion.autenticado) { mostrarClave(); return; }
  } catch (_) { /* si no se sabe, se intenta entrar y el 401 dira lo suyo */ }
  await arrancar();
})();
