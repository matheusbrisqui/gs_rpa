"""Endereço aproximado a partir da coordenada (Nominatim / OpenStreetMap).

O endereço enriquece o chamado, mas não é essencial: qualquer falha aqui é registrada
e o processamento segue sem endereço. Depois de 3 falhas seguidas o serviço é desligado
até o fim da execução, para não atrasar o lote (disjuntor).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

FALHAS_PARA_DESLIGAR = 3


class Geocodificador:
    def __init__(
        self,
        url: str | None,
        *,
        intervalo_s: float = 1.1,
        timeout_s: float = 8.0,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ):
        self._url = url
        self._intervalo_s = intervalo_s
        self._dormir = dormir
        self._relogio = relogio
        self._log = logger or logging.getLogger(__name__)
        self._http = httpx.Client(
            timeout=timeout_s,
            transport=transport,
            headers={"User-Agent": "PassoLivre-RPA/1.0 (projeto academico FIAP)", "Accept-Language": "pt-BR"},
        )
        self._cache: dict[tuple[float, float], str | None] = {}
        self._ultima_chamada: float | None = None
        self._falhas_seguidas = 0
        self.falhas = 0
        self.ativo = bool(url)

    def fechar(self) -> None:
        self._http.close()

    def endereco(self, lat: float, lon: float) -> str | None:
        if not self.ativo:
            return None
        chave = (round(lat, 5), round(lon, 5))
        if chave in self._cache:
            return self._cache[chave]
        self._respeitar_intervalo()
        try:
            resp = self._http.get(
                self._url,
                params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1},
            )
            resp.raise_for_status()
            texto = self._formatar(resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            self.falhas += 1
            self._falhas_seguidas += 1
            self._log.warning("Geocodificação falhou (%s); seguindo sem endereço", type(exc).__name__)
            if self._falhas_seguidas >= FALHAS_PARA_DESLIGAR:
                self.ativo = False
                self._log.warning("Geocodificação desligada até o fim da execução após %d falhas", self.falhas)
            return None
        self._falhas_seguidas = 0
        self._cache[chave] = texto
        return texto

    def _respeitar_intervalo(self) -> None:
        agora = self._relogio()
        if self._ultima_chamada is not None:
            falta = self._intervalo_s - (agora - self._ultima_chamada)
            if falta > 0:
                self._dormir(falta)
        self._ultima_chamada = self._relogio()

    @staticmethod
    def _formatar(dados: dict) -> str | None:
        end = dados.get("address") or {}
        rua = end.get("road") or end.get("pedestrian") or end.get("footway")
        if not rua:
            nome = dados.get("display_name")
            return nome[:120] if nome else None
        partes = [rua + (f", {end['house_number']}" if end.get("house_number") else "")]
        bairro = end.get("suburb") or end.get("neighbourhood") or end.get("city_district")
        if bairro:
            partes.append(bairro)
        return " - ".join(partes)
