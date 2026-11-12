"""Cliente da API do MVP com novas tentativas e espera progressiva (resiliência)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx


class ApiIndisponivel(Exception):
    """A API não respondeu (rede, timeout ou erro 5xx) depois de todas as tentativas."""


class ApiErro(Exception):
    """A API respondeu, mas recusou a requisição (4xx). Tentar de novo não resolve."""

    def __init__(self, status_code: int, detalhe: str):
        super().__init__(f"HTTP {status_code}: {detalhe}")
        self.status_code = status_code


class CredencialRecusada(ApiErro):
    """A API recusou o token da automação (401/403). Nenhum item do lote vai passar: é para abortar."""


class MvpClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        timeout_s: float = 10.0,
        tentativas: int = 3,
        espera_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ):
        cabecalhos = {"User-Agent": "PassoLivre-RPA/1.0"}
        if token:
            cabecalhos["X-Automation-Token"] = token
        self._http = httpx.Client(base_url=base_url, headers=cabecalhos, timeout=timeout_s, transport=transport)
        self._tentativas = max(1, tentativas)
        self._espera_s = espera_s
        self._dormir = dormir
        self._log = logger or logging.getLogger(__name__)

    def fechar(self) -> None:
        self._http.close()

    # ---- operações de negócio -------------------------------------------------
    def saude(self) -> dict:
        return self._requisitar("GET", "/health")

    def listar_relatos(self, *, status: str | None = None, protocolo: str | None = None) -> list[dict]:
        params = {"limite": 2000}
        if status:
            params["status"] = status
        if protocolo:
            params["protocolo"] = protocolo
        return self._requisitar("GET", "/relatos", params=params)

    def listar_pontos(self) -> list[dict]:
        return self._requisitar("GET", "/pontos")

    def atualizar_relato(self, relato_id: int, **campos: Any) -> dict:
        return self._requisitar("PATCH", f"/relatos/{relato_id}", json=campos)

    # ---- transporte com novas tentativas --------------------------------------
    def _requisitar(self, metodo: str, caminho: str, **kwargs: Any) -> Any:
        ultimo_erro = "sem resposta"
        for tentativa in range(1, self._tentativas + 1):
            try:
                resp = self._http.request(metodo, caminho, **kwargs)
            except httpx.TransportError as exc:  # conexão recusada, DNS, timeout...
                ultimo_erro = type(exc).__name__
            else:
                if resp.status_code < 400:
                    return resp.json()
                if resp.status_code in (401, 403):
                    raise CredencialRecusada(resp.status_code, "token de automação recusado; confira AUTOMATION_TOKEN")
                if resp.status_code < 500 and resp.status_code != 429:
                    raise ApiErro(resp.status_code, resp.text[:200])
                ultimo_erro = f"HTTP {resp.status_code}"
            if tentativa < self._tentativas:
                espera = self._espera_s * 2 ** (tentativa - 1)
                self._log.warning(
                    "%s %s falhou (%s). Tentativa %d de %d; nova tentativa em %.1fs",
                    metodo, caminho, ultimo_erro, tentativa, self._tentativas, espera,
                )
                self._dormir(espera)
        raise ApiIndisponivel(f"{metodo} {caminho}: {ultimo_erro} após {self._tentativas} tentativa(s)")
