"""Linha de comando: `python -m passo_livre_rpa` (uma execução) ou `--loop` (execução contínua)."""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time

from .config import Config
from .robo import executar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="passo_livre_rpa", description="Triagem e encaminhamento de relatos do Passo Livre")
    parser.add_argument("--api-url", help="URL da API do MVP (padrão: variável PASSOLIVRE_API_URL)")
    parser.add_argument("--loop", action="store_true", help="repete a execução indefinidamente")
    parser.add_argument("--intervalo", type=int, default=3600, help="segundos entre execuções no modo --loop (padrão: 3600)")
    parser.add_argument("--sem-geocodificacao", action="store_true", help="não consulta endereço dos relatos")
    parser.add_argument("--silencioso", action="store_true", help="não escreve o log na tela (só nos arquivos)")
    args = parser.parse_args(argv)

    config = Config.do_ambiente()
    if args.api_url:
        config = dataclasses.replace(config, api_url=args.api_url.rstrip("/"))
    if args.sem_geocodificacao:
        config = dataclasses.replace(config, geocoder_url=None)

    while True:
        resumo = executar(config, console=not args.silencioso)
        if not args.loop:
            return resumo.codigo_saida
        try:
            time.sleep(args.intervalo)
        except KeyboardInterrupt:
            return resumo.codigo_saida


if __name__ == "__main__":
    sys.exit(main())
