"""Leitura do arquivo de retorno da prefeitura (situação dos chamados encaminhados).

Formato esperado: CSV separado por ponto e vírgula, UTF-8, com o cabeçalho
`protocolo;situacao;data_conclusao`. O nome do arquivo segue `retorno_prefeitura_*.csv`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

CABECALHO = ["protocolo", "situacao", "data_conclusao"]
SITUACOES = {"EM_ANDAMENTO", "CONCLUIDO", "INDEFERIDO"}
PADRAO_ARQUIVO = "retorno_prefeitura_*.csv"


class ArquivoInvalido(Exception):
    """O arquivo inteiro não pode ser aproveitado (vazio, ilegível ou com cabeçalho errado)."""


@dataclass(frozen=True)
class Retorno:
    protocolo: str
    situacao: str
    data_conclusao: date | None
    linha: int


def localizar(entrada_dir: Path) -> list[Path]:
    return sorted(p for p in entrada_dir.glob(PADRAO_ARQUIVO) if p.is_file())


def ler(caminho: Path) -> tuple[list[Retorno], list[str]]:
    """Devolve (linhas válidas, problemas por linha). Levanta ArquivoInvalido se nada puder ser lido."""
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ArquivoInvalido("arquivo não está em UTF-8") from exc
    linhas = list(csv.reader(texto.splitlines(), delimiter=";"))
    if not linhas:
        raise ArquivoInvalido("arquivo vazio")
    cabecalho = [c.strip().lower() for c in linhas[0]]
    if cabecalho != CABECALHO:
        raise ArquivoInvalido(f"cabeçalho inesperado: {';'.join(linhas[0])[:80]}")

    validas: list[Retorno] = []
    problemas: list[str] = []
    vistos: set[str] = set()
    for numero, campos in enumerate(linhas[1:], start=2):
        if not any(c.strip() for c in campos):
            continue  # linha em branco
        if len(campos) != 3:
            problemas.append(f"linha {numero}: esperava 3 colunas, encontrei {len(campos)}")
            continue
        protocolo, situacao, data_txt = (c.strip() for c in campos)
        situacao = situacao.upper()
        if not protocolo:
            problemas.append(f"linha {numero}: protocolo vazio")
            continue
        if situacao not in SITUACOES:
            problemas.append(f"linha {numero}: situação desconhecida '{situacao[:20]}'")
            continue
        if protocolo in vistos:
            problemas.append(f"linha {numero}: protocolo {protocolo} repetido no arquivo")
            continue
        conclusao = None
        if data_txt:
            try:
                conclusao = date.fromisoformat(data_txt)
            except ValueError:
                problemas.append(f"linha {numero}: data inválida '{data_txt[:20]}'")
                continue
        if situacao == "CONCLUIDO" and conclusao is None:
            problemas.append(f"linha {numero}: chamado concluído sem data de conclusão")
            continue
        vistos.add(protocolo)
        validas.append(Retorno(protocolo, situacao, conclusao, numero))
    return validas, problemas
