"""Configuração por variáveis de ambiente. Nenhuma credencial fica no código."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]  # raiz do repositório

# Município de São Paulo (caixa envolvente): lat_min, lat_max, lon_min, lon_max
AREA_SAO_PAULO = (-24.05, -23.30, -46.90, -46.30)


def carregar_env(caminho: Path) -> None:
    """Lê um arquivo .env simples (CHAVE=valor) sem sobrescrever o que já está no ambiente."""
    if not caminho.is_file():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def _caminho(nome: str, padrao: str) -> Path:
    valor = Path(os.environ.get(nome, padrao))
    return valor if valor.is_absolute() else RAIZ / valor


@dataclass(frozen=True)
class Config:
    api_url: str = "http://127.0.0.1:8000"
    automation_token: str | None = None
    entrada_dir: Path = RAIZ / "entrada"
    saida_dir: Path = RAIZ / "saida"
    logs_dir: Path = RAIZ / "logs"
    raio_duplicado_m: float = 20.0
    janela_duplicado_dias: int = 30
    raio_ponto_m: float = 60.0
    area: tuple[float, float, float, float] = AREA_SAO_PAULO
    geocoder_url: str | None = "https://nominatim.openstreetmap.org/reverse"
    geocoder_intervalo_s: float = 1.1  # política do Nominatim: no máximo 1 requisição por segundo
    http_timeout_s: float = 10.0
    http_tentativas: int = 3
    http_espera_s: float = 2.0

    @classmethod
    def do_ambiente(cls) -> Config:
        carregar_env(RAIZ / ".env")
        env = os.environ.get
        area = env("RPA_AREA")
        return cls(
            api_url=env("PASSOLIVRE_API_URL", cls.api_url).rstrip("/"),
            automation_token=env("AUTOMATION_TOKEN") or None,
            entrada_dir=_caminho("RPA_ENTRADA_DIR", "entrada"),
            saida_dir=_caminho("RPA_SAIDA_DIR", "saida"),
            logs_dir=_caminho("RPA_LOGS_DIR", "logs"),
            raio_duplicado_m=float(env("RPA_RAIO_DUPLICADO_M", cls.raio_duplicado_m)),
            janela_duplicado_dias=int(env("RPA_JANELA_DUPLICADO_DIAS", cls.janela_duplicado_dias)),
            raio_ponto_m=float(env("RPA_RAIO_PONTO_M", cls.raio_ponto_m)),
            area=tuple(float(x) for x in area.split(",")) if area else AREA_SAO_PAULO,  # type: ignore[arg-type]
            geocoder_url=(env("GEOCODER_URL", cls.geocoder_url) or None),
            geocoder_intervalo_s=float(env("GEOCODER_INTERVALO_S", cls.geocoder_intervalo_s)),
            http_timeout_s=float(env("RPA_HTTP_TIMEOUT_S", cls.http_timeout_s)),
            http_tentativas=int(env("RPA_HTTP_TENTATIVAS", cls.http_tentativas)),
            http_espera_s=float(env("RPA_HTTP_ESPERA_S", cls.http_espera_s)),
        )
