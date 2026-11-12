"""Apoio aos testes: uma API do MVP simulada em memória (sem rede) e uma configuração temporária."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from passo_livre_rpa.cliente_api import MvpClient
from passo_livre_rpa.config import Config
from passo_livre_rpa.geocodificador import Geocodificador

AGORA = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
PONTO_MASP = {"codigo": "340015329", "nome": "Av. Paulista - MASP", "lat": -23.56135, "lon": -46.65585}
LONGE_DE_PONTO = (-23.57500, -46.63000)


def relato(rid, *, tipo="buraco", lat=PONTO_MASP["lat"], lon=PONTO_MASP["lon"], perfil="outro", status="novo",
           criado_em="2026-11-10T12:00:00", protocolo=None):
    return {
        "id": rid, "tipo": tipo, "lat": lat, "lon": lon, "perfil": perfil, "status": status,
        "criado_em": criado_em, "protocolo": protocolo, "prioridade": None, "duplicado_de": None,
        # campos que NUNCA podem aparecer em log ou arquivo de saída:
        "descricao": "TEXTO-LIVRE-DO-CIDADAO", "usuario_hash": "HASH-DO-CIDADAO",
    }


class MvpFalso:
    """Imita os endpoints do MVP usados pelo robô e permite injetar falhas."""

    def __init__(self, relatos, pontos=None):
        self.relatos = {r["id"]: dict(r) for r in relatos}
        self.pontos = pontos if pontos is not None else [PONTO_MASP]
        self.fora_do_ar = False
        self.cair_depois_de_patches: int | None = None
        self.patch_erro_500: set[int] = set()
        self.patch_erro_422: set[int] = set()
        self.token_esperado: str | None = None
        self.patches = 0
        self.chamadas: list[tuple[str, str]] = []

    def responder(self, request: httpx.Request) -> httpx.Response:
        self.chamadas.append((request.method, request.url.path))
        if self.fora_do_ar:
            raise httpx.ConnectError("conexão recusada", request=request)
        caminho = request.url.path
        if caminho == "/health":
            return httpx.Response(200, json={"status": "ok", "servico": "Passo Livre API", "versao": "teste"})
        if caminho == "/pontos":
            return httpx.Response(200, json=self.pontos)
        if caminho == "/relatos" and request.method == "GET":
            itens = list(self.relatos.values())
            for campo in ("status", "protocolo"):
                valor = request.url.params.get(campo)
                if valor:
                    itens = [r for r in itens if r.get(campo) == valor]
            return httpx.Response(200, json=itens)
        if caminho.startswith("/relatos/") and request.method == "PATCH":
            if self.token_esperado and request.headers.get("X-Automation-Token") != self.token_esperado:
                return httpx.Response(401, json={"detail": "Token de automação inválido ou ausente"})
            rid = int(caminho.rsplit("/", 1)[1])
            if self.cair_depois_de_patches is not None and self.patches >= self.cair_depois_de_patches:
                raise httpx.ConnectError("conexão recusada", request=request)
            if rid in self.patch_erro_500:
                return httpx.Response(500, text="erro interno")
            if rid in self.patch_erro_422:
                return httpx.Response(422, json={"detail": "dados inválidos"})
            self.relatos[rid].update(json.loads(request.content))
            self.patches += 1
            return httpx.Response(200, json=self.relatos[rid])
        return httpx.Response(404, json={"detail": "não encontrado"})

    def cliente(self, token=None, tentativas=3) -> MvpClient:
        return MvpClient(
            "http://mvp.teste", token, tentativas=tentativas, espera_s=0,
            transport=httpx.MockTransport(self.responder), dormir=lambda _s: None,
        )


def geocodificador(*, falhar=False) -> Geocodificador:
    def responder(request: httpx.Request) -> httpx.Response:
        if falhar:
            raise httpx.ConnectTimeout("tempo esgotado", request=request)
        return httpx.Response(200, json={"address": {"road": "Avenida Paulista", "house_number": "1578", "suburb": "Bela Vista"}})

    return Geocodificador(
        "http://geo.teste/reverse", intervalo_s=0, transport=httpx.MockTransport(responder), dormir=lambda _s: None
    )


@pytest.fixture
def config(tmp_path) -> Config:
    (tmp_path / "entrada").mkdir()
    return Config(
        api_url="http://mvp.teste", entrada_dir=tmp_path / "entrada", saida_dir=tmp_path / "saida",
        logs_dir=tmp_path / "logs", http_espera_s=0, geocoder_intervalo_s=0,
    )


def agora():
    return AGORA
