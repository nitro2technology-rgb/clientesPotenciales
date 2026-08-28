"""
Verificador de credenciales - COSTO $0.00

Comprueba que las 3 credenciales esten bien puestas SIN llamar a Places ni a
Geocoding (que son las APIs que cobran). La API de Sheets no cobra, asi que
esa si se prueba de verdad, incluyendo permiso de escritura.

Uso:  python verificar.py
"""
import json
import sys
from pathlib import Path

from app.config import settings

OK = "[ OK ]"
MAL = "[FALLA]"
AVISO = "[AVISO]"


def titulo(texto: str) -> None:
    print(f"\n{texto}\n" + "-" * len(texto))


def verificar_api_key() -> bool:
    titulo("1 de 3 - API Key (Places + Geocoding)")
    clave = settings.google_maps_api_key

    if not clave:
        print(f"{MAL} GOOGLE_MAPS_API_KEY esta vacia en el .env")
        print("       Pegala en la linea:  GOOGLE_MAPS_API_KEY=AIza...")
        return False

    print(f"{OK} Cargada: {clave[:6]}...{clave[-4:]} ({len(clave)} caracteres)")

    if not clave.startswith("AIza"):
        print(f"{AVISO} Las API Keys de Google suelen empezar por 'AIza'.")
        print("       Revisa que no hayas pegado otra cosa (como el Sheet ID).")
    if " " in clave or '"' in clave:
        print(f"{AVISO} La clave tiene espacios o comillas. La app los limpia,")
        print("       pero es mejor dejarla limpia en el .env.")

    print("       No se prueba contra Google aqui: esa llamada costaria dinero.")
    print("       Se valida sola en tu primera busqueda real.")
    return True


def verificar_service_account() -> tuple[bool, str]:
    titulo("2 de 3 - JSON de la Service Account")
    ruta_texto = settings.google_service_account_file

    if not ruta_texto:
        print(f"{AVISO} GOOGLE_SERVICE_ACCOUNT_FILE esta vacio.")
        print("       Es OPCIONAL: sin esto la app guarda en local y exporta")
        print("       a Excel/CSV igual. Solo pierdes el Google Sheet.")
        return False, ""

    ruta = Path(ruta_texto)
    if not ruta.is_absolute():
        ruta = Path(__file__).parent / ruta

    if not ruta.is_file():
        print(f"{MAL} No existe el archivo: {ruta}")
        print("       Revisa la ruta en el .env. Usa barras normales (/).")
        return False, ""

    print(f"{OK} Archivo encontrado: {ruta}")

    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{MAL} El archivo no es un JSON valido: {exc}")
        return False, ""

    # token_uri y project_id tambien son obligatorios: si faltan, google-auth
    # falla mas adelante con un error mucho menos claro.
    requeridos = ("type", "client_email", "private_key", "token_uri", "project_id")
    faltantes = [c for c in requeridos if c not in datos]
    if faltantes:
        print(f"{MAL} Al JSON le faltan campos: {', '.join(faltantes)}")
        print("       Ese archivo no es la clave completa de la service account.")
        print("       Descargala de nuevo: Google Cloud Console -> IAM ->")
        print("       Cuentas de servicio -> tu cuenta -> Claves -> Agregar clave")
        print("       -> Crear clave nueva -> JSON")
        return False, ""

    if datos.get("type") != "service_account":
        print(f"{MAL} El JSON es de tipo '{datos.get('type')}', no 'service_account'.")
        return False, ""

    email = datos["client_email"]
    print(f"{OK} JSON valido. Cuenta de servicio:")
    print(f"       {email}")
    print("       <- Este email debe tener acceso de EDITOR a tu Sheet.")
    return True, email


def verificar_sheet(email_cuenta: str) -> bool:
    titulo("3 de 3 - Google Sheet (esta prueba es gratis)")

    if not settings.google_sheet_id:
        print(f"{AVISO} GOOGLE_SHEET_ID esta vacio en el .env")
        return False
    if not email_cuenta:
        print(f"{AVISO} Sin Service Account valida no se puede probar el Sheet.")
        return False

    print(f"{OK} Sheet ID: {settings.google_sheet_id}")
    print("       Conectando...")

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        ruta = Path(settings.google_service_account_file)
        if not ruta.is_absolute():
            ruta = Path(__file__).parent / ruta

        credenciales = Credentials.from_service_account_file(
            str(ruta), scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        libro = gspread.authorize(credenciales).open_by_key(settings.google_sheet_id)
        print(f"{OK} Conectado al Sheet: \"{libro.title}\"")

        pestanas = [h.title for h in libro.worksheets()]
        print(f"       Pestanas existentes: {', '.join(pestanas)}")
        if settings.google_sheet_tab in pestanas:
            print(f"{OK} La pestana '{settings.google_sheet_tab}' ya existe.")
        else:
            print(f"{AVISO} No existe la pestana '{settings.google_sheet_tab}'.")
            print("       La app la creara sola en la primera busqueda.")

        # Prueba de ESCRITURA real: sin esto no sabriamos si es solo lectura.
        hoja = libro.sheet1
        celda_original = hoja.acell("Z999").value
        hoja.update(values=[["prueba"]], range_name="Z999")
        if celda_original is None:
            hoja.batch_clear(["Z999"])
        else:
            hoja.update(values=[[celda_original]], range_name="Z999")
        print(f"{OK} Permiso de ESCRITURA confirmado (celda de prueba borrada).")
        return True

    except Exception as exc:
        nombre = type(exc).__name__
        print(f"{MAL} No se pudo conectar ({nombre})")
        texto = str(exc)
        if "404" in texto or "not found" in texto.lower():
            print("       El Sheet ID no existe o esta mal copiado.")
            print("       Copialo de la URL, entre /d/ y /edit")
        elif "403" in texto or "permission" in texto.lower():
            print(f"       El Sheet NO esta compartido con: {email_cuenta}")
            print("       Abre tu Sheet -> Compartir -> pega ese email -> Editor")
        elif "PEM" in texto or "private key" in texto.lower():
            print("       La clave privada dentro del JSON esta corrupta.")
            print("       Suele pasar si el archivo se edito o se copio a mano.")
            print("       Descarga el JSON de nuevo sin abrirlo ni modificarlo.")
        elif "api" in texto.lower() and "disabled" in texto.lower():
            print("       Falta habilitar la Google Sheets API en tu proyecto.")
            print("       Console -> APIs y servicios -> Biblioteca -> Google Sheets API")
        else:
            print(f"       {texto[:220]}")
        return False


def verificar_base_de_datos() -> bool:
    """
    Comprueba donde vive la base y que responda. No gasta dinero: Turso es
    gratis y esto es una consulta trivial.
    """
    titulo("Base de datos")

    if not settings.usa_turso:
        from app.storage import DB_PATH
        existe = Path(DB_PATH).is_file()
        print(f"  Local (SQLite): {DB_PATH}")
        print(f"  {'Existe, se usara tal cual.' if existe else 'Aun no existe: se creara en la primera busqueda.'}")
        print("  (Para el despliegue hace falta Turso: rellena TURSO_* en el .env)")
        return True

    print(f"  Turso: {settings.turso_database_url}")
    try:
        from app import turso
        con = turso.conectar(settings.turso_database_url, settings.turso_auth_token)
        try:
            fila = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
            tablas = fila[0]
            if tablas == 0:
                print("  Conecta, pero esta VACIA (sin tablas).")
                print("  Sube tu historico con:  python migrar_a_turso.py")
                return True
            negocios = con.execute("SELECT COUNT(*) FROM negocios").fetchone()[0]
            print(f"  Conecta. {tablas} tablas, {negocios} negocios guardados.")
            return True
        finally:
            con.close()
    except Exception as exc:
        print(f"  NO conecta: {exc}")
        print("  Revisa TURSO_DATABASE_URL y TURSO_AUTH_TOKEN, y que la base")
        print("  siga activa en turso.tech.")
        return False


def main() -> int:
    print("=" * 66)
    print("  VERIFICACION DE CREDENCIALES - no gasta dinero")
    print("=" * 66)
    print(f"  Modo demo: {'SI (no se llama a Google)' if settings.demo_mode else 'NO - modo real'}")

    key_ok = verificar_api_key()
    base_ok = verificar_base_de_datos()
    cuenta_ok, email = verificar_service_account()
    sheet_ok = verificar_sheet(email) if cuenta_ok else False

    titulo("Resumen")
    print(f"  API Key .............. {'lista' if key_ok else 'FALTA'}")
    destino = "Turso (nube)" if settings.usa_turso else "local (data/leads.db)"
    print(f"  Base de datos ........ {destino if base_ok else 'NO RESPONDE'}")
    print(f"  Service Account ...... {'lista' if cuenta_ok else 'no configurada'}")
    print(f"  Google Sheet ......... {'conectado' if sheet_ok else 'no conectado'}")

    if key_ok and sheet_ok:
        print("\n  Todo listo. Ya puedes hacer tu primera busqueda real.")
    elif key_ok:
        print("\n  Puedes buscar: los datos se guardaran en local y en Excel/CSV.")
        print("  El Google Sheet no recibira nada hasta que lo arregles.")
    else:
        print("\n  Falta la API Key: las busquedas fallaran. Revisa el .env.")

    print("\n  Siguiente paso:  python run.py")
    print("=" * 66)
    return 0 if key_ok else 1


if __name__ == "__main__":
    sys.exit(main())
