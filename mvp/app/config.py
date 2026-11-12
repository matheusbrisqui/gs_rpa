"""Configuração via variáveis de ambiente (nunca segredos no código)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # O mesmo arquivo .env da raiz serve ao aplicativo e ao robô.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Passo Livre API"
    database_url: str = "sqlite:///./passolivre.db"
    seed_demo: bool = True  # carrega dados de demonstração quando o banco está vazio
    hash_salt: str = "troque-este-salt-em-producao"  # LGPD: hash do identificador do cidadão
    cors_origins: str = "*"
    # Token do robô. Quando definido, PATCH /relatos exige o cabeçalho X-Automation-Token.
    automation_token: str | None = None


settings = Settings()
