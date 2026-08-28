"""Lanzador de la app. Uso: python run.py"""
import uvicorn

from app.config import settings

LINEA = "=" * 66


def _banner() -> None:
    print(LINEA)
    print("  Generador de Leads desde Google Maps")
    print(LINEA)

    if settings.demo_mode:
        print("  MODO: DEMO - datos de ejemplo, no se llama a Google.")
        print("        Costo: $0.00. Ninguna busqueda gasta dinero.")
    else:
        print("  MODO: REAL - las busquedas SI llaman a Google y SI cuestan.")
        if not settings.google_maps_api_key:
            print()
            print("  !! FALTA LA API KEY")
            print("     Pega GOOGLE_MAPS_API_KEY en el archivo .env")
            print("     Las busquedas fallaran hasta que la configures.")
        else:
            clave = settings.google_maps_api_key
            print(f"  API Key: {clave[:6]}...{clave[-4:]}  (cargada desde .env)")

        print()
        print("  Salvaguardas activas:")
        print(f"    - Tope diario ............. {settings.max_requests_per_day} requests")
        print(f"    - Paginas por busqueda .... {settings.max_pages_per_search} maximo")
        confirmacion = "SI" if settings.confirmar_antes_de_gastar else "NO"
        print(f"    - Confirmar antes de gastar {confirmacion}")
        if not settings.confirmar_antes_de_gastar:
            print("      (recomendado: pon CONFIRMAR_ANTES_DE_GASTAR=true en .env)")
        print()
        print("  Recuerda que la proteccion definitiva es la alerta de")
        print("  presupuesto y las cuotas en Google Cloud Console.")

    print()
    if settings.sheets_habilitado:
        print(f"  Google Sheets: conectado -> {settings.sheet_url}")
    elif settings.google_sheet_id or settings.google_service_account_file:
        print("  Google Sheets: configurado a medias, revisa el .env")
        print("    (hace falta GOOGLE_SERVICE_ACCOUNT_FILE valido + GOOGLE_SHEET_ID)")
        print("    Ejecuta:  python verificar.py")
    else:
        print("  Google Sheets: no configurado (se guarda solo en local)")

    print()
    print(f"  Abre en el navegador:  http://{settings.host}:{settings.port}")
    print("  Ctrl+C para detener")
    print(LINEA)


if __name__ == "__main__":
    _banner()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
