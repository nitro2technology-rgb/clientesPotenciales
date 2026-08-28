"""Configuracion leida desde variables de entorno (.env)."""
import json
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Google APIs
    google_maps_api_key: str = ""

    # Google Sheets (opcional)
    google_service_account_file: str = ""
    # Alternativa para servidores sin disco propio (Vercel): el JSON completo
    # de la service account pegado tal cual en una variable de entorno.
    google_service_account_json: str = ""
    google_sheet_id: str = ""
    google_sheet_tab: str = "Leads"

    # Base de datos remota (Turso / libSQL). Si estan vacias, se usa el
    # SQLite local de siempre en data/leads.db.
    turso_database_url: str = ""
    turso_auth_token: str = ""

    # Control de costos
    max_requests_per_day: int = 200
    max_pages_per_search: int = 3
    confirmar_antes_de_gastar: bool = True
    # Cuantos sectores explora como maximo cada vez que pulsas Buscar.
    # Es el freno principal del costo en modo campana.
    celdas_por_sesion: int = 5

    # Modo demo (sin llamadas reales a Google)
    demo_mode: bool = False

    # Servidor
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator(
        "google_maps_api_key",
        "google_service_account_file",
        "google_sheet_id",
        "google_sheet_tab",
        "turso_database_url",
        "turso_auth_token",
        mode="before",
    )
    @classmethod
    def _limpiar(cls, valor):
        """
        Quita espacios y comillas sobrantes al pegar valores en el .env.

        Es facil pegar la ruta entre comillas o dejar un espacio al final.
        Sin esto, la credencial no funcionaria y el error seria confuso.
        """
        if not isinstance(valor, str):
            return valor
        return valor.strip().strip('"').strip("'").strip()

    @property
    def usa_turso(self) -> bool:
        """True cuando la base de datos vive en Turso en vez de en disco."""
        return bool(self.turso_database_url and self.turso_auth_token)

    @property
    def credenciales_sheets(self) -> dict | None:
        """
        El JSON de la service account, venga de donde venga.

        Prioriza la variable de entorno porque es la unica via en un
        servidor sin disco persistente. Devuelve None si no hay nada usable.
        """
        crudo = self.google_service_account_json.strip()
        if crudo:
            try:
                return json.loads(crudo)
            except json.JSONDecodeError:
                return None
        ruta = self.google_service_account_file
        if ruta and Path(ruta).is_file():
            try:
                return json.loads(Path(ruta).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    @property
    def sheets_habilitado(self) -> bool:
        return bool(self.google_sheet_id and self.credenciales_sheets)

    @property
    def sheet_url(self) -> str:
        if not self.google_sheet_id:
            return ""
        return f"https://docs.google.com/spreadsheets/d/{self.google_sheet_id}"


settings = Settings()

# En serverless (Vercel) el disco es de solo lectura y la base vive en Turso:
# intentar crear la carpeta reventaria el arranque de la app.
if not settings.usa_turso:
    try:
        DIR_DATOS.mkdir(exist_ok=True)
    except OSError:
        pass
