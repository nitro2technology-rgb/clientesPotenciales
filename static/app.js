// -------------------------------------------------------------- utilidades
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const esc = (txt) =>
  String(txt ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

let RESULTADO = null;
let FILTRO = "leads";
let ESTADO = null;
let CAMPANA = null;   // progreso de la campaña actual (ciudad + categoría)

// Categorías sugeridas: etiqueta visible -> tipo de Places para el modo "tipo"
const CATEGORIAS = [
  ["peluquerías", "hair_salon"],
  ["barberías", "barber_shop"],
  ["restaurantes", "restaurant"],
  ["cafeterías", "cafe"],
  ["panaderías", "bakery"],
  ["gimnasios", "gym"],
  ["veterinarias", "veterinary_care"],
  ["ferreterías", "hardware_store"],
  ["talleres mecánicos", "car_repair"],
  ["odontólogos", "dentist"],
  ["spa", "spa"],
  ["floristerías", "florist"],
  ["lavanderías", "laundry"],
  ["ópticas", "optician"],
  ["hoteles", "hotel"],
  ["inmobiliarias", "real_estate_agency"],
  ["abogados", "lawyer"],
  ["tiendas de ropa", "clothing_store"],
  ["joyerías", "jewelry_store"],
  ["farmacias", "pharmacy"],
];

// ------------------------------------------------------------------ estado
async function cargarEstado() {
  try {
    ESTADO = await (await fetch("/api/estado")).json();
  } catch {
    return;
  }
  const chips = [];

  if (ESTADO.demo_mode) {
    chips.push(`<span class="chip alerta">MODO DEMO · no se llama a Google</span>`);
  } else if (!ESTADO.api_key_configurada) {
    chips.push(`<span class="chip alerta">Falta API Key en .env</span>`);
  } else {
    chips.push(`<span class="chip ok">API conectada</span>`);
  }

  chips.push(
    ESTADO.sheets_habilitado
      ? `<span class="chip ok">Google Sheets activo</span>`
      : `<span class="chip">Sheets no configurado · guarda local</span>`
  );
  chips.push(
    `<span class="chip">${ESTADO.requests_restantes} / ${ESTADO.max_requests_dia} requests hoy</span>`
  );

  $("#estado-chips").innerHTML = chips.join("");
  $("#footer-uso").textContent =
    `Consumo de hoy (${ESTADO.dia}): ${ESTADO.requests_hoy} requests · ` +
    `tope diario ${ESTADO.max_requests_dia} (editable en .env)`;
  $("#lista-redes").textContent = ESTADO.redes_sociales_activas.join(", ");

  if (ESTADO.sheet_url) {
    const link = $("#link-sheet");
    link.href = ESTADO.sheet_url;
    link.classList.remove("oculto");
  }
  actualizarCosto();
}

// -------------------------------------------------------------- estimación
/**
 * Calcula el costo máximo de la búsqueda que está configurada ahora mismo.
 * Devuelve el desglose para poder mostrarlo línea por línea en el modal.
 */
function estimar() {
  const modo = $("#modo").value;
  const esCampana = $("#campana").checked;
  const paginasPorBusqueda = modo === "tipo" ? 1 : Number($("#paginas").value);
  const conRating = $("#incluir-rating").checked;
  const precioBusqueda = conRating
    ? ESTADO.precio_1000_con_rating
    : ESTADO.precio_1000_sin_rating;

  // Si la ciudad ya se geocodificó antes, está en caché y no se vuelve a pagar.
  const ciudad = $("#ciudad").value.trim().toLowerCase();
  const yaEnCache = (ESTADO.ciudades_ya_geocodificadas || []).includes(ciudad);
  // En una campaña ya empezada, la ciudad se geocodificó en la primera sesión.
  const geocoding = yaEnCache || (esCampana && CAMPANA?.existe) ? 0 : 1;

  const lineas = [];
  lineas.push(
    geocoding
      ? {
          concepto: "Convertir la ciudad en coordenadas (Geocoding)",
          detalle: "1 request",
          costo: ESTADO.precio_1000_geocoding / 1000,
        }
      : { concepto: "Geocoding", detalle: "ya en caché · gratis", costo: 0 }
  );

  let requestsBusqueda;
  if (esCampana) {
    // Se exploran N sectores, pero nunca más de los que quedan pendientes.
    let sectores = Number($("#sectores").value);
    if (CAMPANA?.existe) {
      sectores = Math.min(sectores, CAMPANA.celdas_pendientes);
    }
    requestsBusqueda = sectores * paginasPorBusqueda;
    lineas.push({
      concepto: `Barrido de ${sectores} sector${sectores === 1 ? "" : "es"}` +
        `${conRating ? " con rating y reseñas" : ""}`,
      detalle:
        `${sectores} × ${paginasPorBusqueda} página(s) = ` +
        `${requestsBusqueda} requests · hasta ${requestsBusqueda * 20} negocios`,
      costo: (requestsBusqueda * precioBusqueda) / 1000,
    });
  } else {
    requestsBusqueda = paginasPorBusqueda;
    lineas.push({
      concepto: `Búsqueda de negocios${conRating ? " con rating y reseñas" : ""}`,
      detalle:
        `${requestsBusqueda} request${requestsBusqueda > 1 ? "s" : ""} · ` +
        `hasta ${requestsBusqueda * 20} negocios`,
      costo: (requestsBusqueda * precioBusqueda) / 1000,
    });
  }

  const requests = geocoding + requestsBusqueda;
  const total = lineas.reduce((suma, l) => suma + l.costo, 0);
  return { lineas, requests, total };
}

// ------------------------------------------------------- estado de campaña
/**
 * Consulta el progreso de la campaña (ciudad + categoría). Es gratis: no
 * llama a Google, solo lee la base de datos local.
 */
async function cargarCampana() {
  const ciudad = $("#ciudad").value.trim();
  const categoria = $("#categoria").value.trim();
  const panel = $("#progreso-campana");

  if (!$("#campana").checked || ciudad.length < 2 || categoria.length < 2) {
    panel.classList.add("oculto");
    CAMPANA = null;
    actualizarCosto();
    return;
  }

  try {
    const params = new URLSearchParams({ ciudad, categoria, modo: $("#modo").value });
    CAMPANA = await (await fetch(`/api/campana/estado?${params}`)).json();
  } catch {
    CAMPANA = null;
  }
  pintarProgreso();
  actualizarCosto();
}

function pintarProgreso() {
  const panel = $("#progreso-campana");

  if (!CAMPANA?.existe) {
    panel.classList.add("oculto");
    return;
  }

  const p = CAMPANA;
  panel.classList.remove("oculto");
  panel.classList.toggle("completa", p.terminada);
  $("#barra-relleno").style.width = `${p.porcentaje}%`;
  $("#progreso-pct").textContent = `${p.porcentaje}%`;

  if (p.terminada) {
    $("#progreso-texto").textContent = "Zona explorada por completo";
    $("#progreso-detalle").textContent =
      `Se recorrieron los ${p.total_celdas} sectores y se sacaron ` +
      `${p.negocios_nuevos_acumulados} negocios. Google no tiene más para esta ` +
      `combinación: prueba otra palabra clave o amplía el radio.`;
  } else {
    $("#progreso-texto").textContent =
      `Barrido en curso: ${p.celdas_exploradas} de ${p.total_celdas} sectores`;
    $("#progreso-detalle").textContent =
      `Quedan ${p.celdas_pendientes} sectores por explorar · ` +
      `${p.negocios_nuevos_acumulados} negocios encontrados hasta ahora`;
  }
}

function actualizarCosto() {
  if (!ESTADO) return;
  if (ESTADO.demo_mode) {
    $("#costo-previo").textContent = "Modo demo: costo $0.00";
    return;
  }
  const { requests, total } = estimar();
  $("#costo-previo").textContent =
    `Costo estimado: hasta $${total.toFixed(3)} USD (${requests} request${
      requests > 1 ? "s" : ""
    })`;
}

// --------------------------------------------- confirmación antes de gastar
/**
 * Muestra el modal con el desglose de costo. Devuelve una promesa que
 * resuelve a true si el usuario confirma, false si cancela.
 * En modo demo, o si CONFIRMAR_ANTES_DE_GASTAR=false, no pregunta.
 */
function confirmarCosto() {
  if (ESTADO.demo_mode || !ESTADO.confirmar_antes_de_gastar) {
    return Promise.resolve(true);
  }

  const { lineas, requests, total } = estimar();

  $("#desglose-cuerpo").innerHTML = lineas
    .map(
      (l) => `<tr>
        <td class="concepto">${esc(l.concepto)}<div class="sub">${esc(l.detalle)}</div></td>
        <td>$${l.costo.toFixed(4)}</td>
      </tr>`
    )
    .join("");
  $("#desglose-total").textContent = `$${total.toFixed(3)} USD`;

  const restantes = ESTADO.requests_restantes;
  const cuota = $("#modal-cuota");
  cuota.textContent =
    `Esta búsqueda usa ${requests} de los ${restantes} requests que te quedan hoy ` +
    `(tope diario: ${ESTADO.max_requests_dia}).`;
  cuota.classList.toggle("peligro", requests > restantes);
  if (requests > restantes) {
    cuota.textContent =
      `No alcanza: esta búsqueda necesita ${requests} requests y solo te quedan ` +
      `${restantes} hoy. Sube MAX_REQUESTS_PER_DAY en el .env si lo necesitas.`;
  }

  $("#modal-costo").classList.remove("oculto");
  $("#modal-confirmar").focus();

  return new Promise((resolver) => {
    const cerrar = (respuesta) => {
      $("#modal-costo").classList.add("oculto");
      $("#modal-confirmar").onclick = null;
      $("#modal-cancelar").onclick = null;
      document.removeEventListener("keydown", alPulsarTecla);
      resolver(respuesta);
    };
    const alPulsarTecla = (evento) => {
      if (evento.key === "Escape") cerrar(false);
    };
    $("#modal-confirmar").onclick = () => cerrar(true);
    $("#modal-cancelar").onclick = () => cerrar(false);
    document.addEventListener("keydown", alPulsarTecla);
  });
}

// ----------------------------------------------------------------- mensajes
function mostrarMensaje(texto, tipo = "info", lista = []) {
  const caja = $("#mensaje");
  caja.className = tipo;
  caja.innerHTML =
    `<div>${esc(texto)}</div>` +
    (lista.length
      ? `<ul>${lista.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`
      : "");
  caja.classList.remove("oculto");
}

function ocultarMensaje() {
  $("#mensaje").classList.add("oculto");
}

// ------------------------------------------------------------------ render
function badge(negocio) {
  if (!negocio.es_lead) return `<span class="badge no">Ya tiene web</span>`;
  if (negocio.motivo.includes("red social"))
    return `<span class="badge social">Solo red social</span>`;
  return `<span class="badge lead">Sin web</span>`;
}

function filtrar(negocios) {
  if (FILTRO === "leads") return negocios.filter((n) => n.es_lead);
  if (FILTRO === "con-web") return negocios.filter((n) => !n.es_lead);
  return negocios;
}

function pintarResumen(r) {
  const costo = r.demo ? "$0.00" : `$${r.costo_estimado_usd.toFixed(3)}`;

  // En barrido, lo relevante es cuántos NUEVOS entraron y cuántos duplicados
  // se evitaron. En búsqueda suelta, el total encontrado.
  const esCampana = r.progreso !== undefined;
  const totalMostrado = esCampana ? r.total_nuevos : r.total_encontrados;
  const tercera = esCampana
    ? `<div class="stat descartados">
         <div class="valor">${r.ya_conocidos_descartados}</div>
         <div class="etiqueta">Duplicados evitados (ya los tenías)</div>
       </div>`
    : `<div class="stat">
         <div class="valor">${r.total_ya_tienen_web}</div>
         <div class="etiqueta">Ya tienen sitio propio</div>
       </div>`;

  $("#resumen").innerHTML = `
    <div class="stat destacado">
      <div class="valor">${r.total_leads}</div>
      <div class="etiqueta">Leads válidos (sin web propia)</div>
    </div>
    <div class="stat">
      <div class="valor">${totalMostrado}</div>
      <div class="etiqueta">${esCampana ? "Negocios nuevos" : "Negocios encontrados"}</div>
    </div>
    ${tercera}
    <div class="stat costo">
      <div class="valor">${costo}</div>
      <div class="etiqueta">${r.requests_usados} requests · quedan ${r.requests_restantes_hoy} hoy</div>
    </div>`;
  $("#resumen").classList.remove("oculto");
}

function pintarTabla() {
  const filas = filtrar(RESULTADO.negocios);
  const cuerpo = $("#tabla tbody");

  cuerpo.innerHTML = filas
    .map((n) => {
      const web = n.sitio_web
        ? `<a href="${esc(n.sitio_web)}" target="_blank" rel="noopener">${esc(
            n.sitio_web.replace(/^https?:\/\/(www\.)?/, "").slice(0, 38)
          )}</a>`
        : `<span class="sin-dato">— sin web —</span>`;
      const tel = n.telefono
        ? `<a href="tel:${esc(n.telefono.replace(/\s/g, ""))}">${esc(n.telefono)}</a>`
        : `<span class="sin-dato">—</span>`;
      const rating =
        n.rating != null
          ? `${n.rating} <span class="sub">(${n.resenas ?? 0})</span>`
          : `<span class="sin-dato">—</span>`;
      const maps = n.maps_url
        ? `<a href="${esc(n.maps_url)}" target="_blank" rel="noopener">Ver</a>`
        : `<span class="sin-dato">—</span>`;
      return `<tr>
        <td><div class="nombre">${esc(n.nombre)}</div>
            <div class="sub">${esc(n.categoria_google)}</div></td>
        <td>${tel}</td>
        <td>${web}</td>
        <td>${badge(n)}<div class="sub">${esc(n.motivo)}</div></td>
        <td>${rating}</td>
        <td class="sub">${esc(n.direccion)}</td>
        <td>${maps}</td>
      </tr>`;
    })
    .join("");

  $("#vacio").classList.toggle("oculto", filas.length > 0);
  $("#panel-resultados").classList.remove("oculto");
}

// --------------------------------------------------------------- búsqueda
async function buscar(evento) {
  evento.preventDefault();

  // Antes de gastar un solo peso: mostrar el desglose y pedir confirmación.
  if (!(await confirmarCosto())) {
    mostrarMensaje("Búsqueda cancelada. No se gastó nada.", "aviso");
    return;
  }

  const boton = $("#btn-buscar");
  boton.disabled = true;
  boton.classList.add("cargando");
  boton.textContent = "Buscando";
  ocultarMensaje();

  const cuerpo = {
    ciudad: $("#ciudad").value.trim(),
    categoria: $("#categoria").value.trim(),
    radio_km: Number($("#radio").value),
    modo: $("#modo").value,
    max_paginas: Number($("#paginas").value),
  };

  // En modo "categoría exacta" hay que mandar el tipo de Places, no la etiqueta
  if (cuerpo.modo === "tipo") {
    const encontrado = CATEGORIAS.find(
      ([etiqueta]) => etiqueta.toLowerCase() === cuerpo.categoria.toLowerCase()
    );
    if (encontrado) cuerpo.categoria = encontrado[1];
  }

  const esCampana = $("#campana").checked;
  const params = new URLSearchParams({
    incluir_rating: $("#incluir-rating").checked,
    guardar: $("#guardar").checked,
  });
  if (esCampana) params.set("max_celdas", $("#sectores").value);

  const endpoint = esCampana ? "/api/campana/buscar" : "/api/buscar";

  try {
    const respuesta = await fetch(`${endpoint}?${params}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
    const datos = await respuesta.json();

    if (!respuesta.ok) {
      const detalle = datos.detail;
      mostrarMensaje(
        typeof detalle === "string" ? detalle : "No se pudo completar la búsqueda.",
        "error"
      );
      return;
    }

    RESULTADO = datos;
    pintarResumen(datos);
    pintarTabla();

    // Refrescar la barra de progreso con lo que acaba de devolver el barrido.
    if (datos.progreso) {
      CAMPANA = { existe: true, ...datos.progreso };
      pintarProgreso();
    }

    if (datos.avisos?.length) {
      mostrarMensaje(
        datos.terminada ? "Zona explorada por completo:" : "Detalles de la búsqueda:",
        datos.terminada ? "aviso" : "info",
        datos.avisos
      );
    }

    const encontrados = datos.progreso ? datos.total_nuevos : datos.total_encontrados;
    if (encontrados === 0 && !datos.avisos?.length) {
      mostrarMensaje(
        "No se encontraron negocios nuevos. Prueba otra palabra clave o un radio mayor.",
        "aviso"
      );
    }
  } catch (error) {
    mostrarMensaje(`Error de conexión con el servidor: ${error.message}`, "error");
  } finally {
    boton.disabled = false;
    boton.classList.remove("cargando");
    boton.textContent = "Buscar negocios";
    // Siempre, incluso si fallo: un request rechazado por Google igual se
    // conto contra la cuota del dia, y el contador debe reflejarlo.
    cargarEstado();
  }
}

// -------------------------------------------------------------- descargas
async function descargar(formato) {
  if (!RESULTADO) return;
  const soloLeads = FILTRO === "leads";
  const p = RESULTADO.parametros || {};
  const etiqueta = `${p.ciudad || ""}_${p.categoria || ""}`.trim() || "leads";

  // Se mandan las filas que ya estan en pantalla en vez de pedirlas por id.
  // Asi la descarga funciona aunque el servidor no guarde estado entre
  // peticiones (es el caso al estar desplegado) y aunque la busqueda se
  // hiciera con "guardar" desactivado.
  const params = new URLSearchParams({
    etiqueta,
    solo_leads: soloLeads,
  });

  try {
    const respuesta = await fetch(`/api/descargar/${formato}?${params}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(RESULTADO.negocios || []),
    });

    if (!respuesta.ok) {
      let detalle = "No se pudo generar el archivo.";
      try {
        const datos = await respuesta.json();
        if (typeof datos.detail === "string") detalle = datos.detail;
      } catch (_) {}
      mostrarMensaje(detalle, "error");
      return;
    }

    const blob = await respuesta.blob();
    const cabecera = respuesta.headers.get("Content-Disposition") || "";
    const nombre =
      cabecera.match(/filename="?([^"]+)"?/)?.[1] || `leads.${formato}`;

    const url = URL.createObjectURL(blob);
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = nombre;
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    mostrarMensaje(`No se pudo descargar el archivo: ${error.message}`, "error");
  }
}

// ------------------------------------------------------------------ init
function init() {
  $("#categorias-sugeridas").innerHTML = CATEGORIAS.map(
    ([etiqueta]) => `<option value="${etiqueta}"></option>`
  ).join("");

  $("#radio").addEventListener("input", (e) => {
    $("#radio-valor").textContent = `${e.target.value} km`;
  });

  ["#paginas", "#incluir-rating", "#sectores"].forEach((sel) =>
    $(sel).addEventListener("change", actualizarCosto)
  );
  // Ciudad, categoría, modo y el toggle de barrido cambian la campaña activa,
  // así que hay que releer su progreso (consulta local, gratis).
  ["#modo", "#campana"].forEach((sel) =>
    $(sel).addEventListener("change", cargarCampana)
  );
  let temporizador;
  ["#ciudad", "#categoria"].forEach((sel) =>
    $(sel).addEventListener("input", () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(cargarCampana, 350);
    })
  );

  $("#form-busqueda").addEventListener("submit", buscar);
  $("#btn-xlsx").addEventListener("click", () => descargar("xlsx"));
  $("#btn-csv").addEventListener("click", () => descargar("csv"));

  $$(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      $$(".tab").forEach((t) => t.classList.remove("activo"));
      tab.classList.add("activo");
      FILTRO = tab.dataset.filtro;
      if (RESULTADO) pintarTabla();
    })
  );

  cargarEstado().then(cargarCampana);
}

init();
