"""Grava em tests/evidencias/ o estado dos relatos no aplicativo, para comparar antes e depois do robô.

Guarda só o que interessa à auditoria (identificador, tipo, situação, prioridade, protocolo).
Descrição, perfil e hash do cidadão ficam de fora.

Uso (com o aplicativo no ar):
    python tests/registrar_estado.py 01_estado_mvp_antes [--api-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

EVIDENCIAS = Path(__file__).resolve().parent / "evidencias"
CAMPOS = ("id", "tipo", "status", "prioridade", "protocolo", "duplicado_de")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("nome", help="nome do arquivo, sem extensão")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        resposta = httpx.get(f"{args.api_url}/relatos", params={"limite": 2000}, timeout=10)
        resposta.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Não foi possível falar com o aplicativo em {args.api_url}: {type(exc).__name__}", file=sys.stderr)
        return 1
    relatos = sorted(({c: r.get(c) for c in CAMPOS} for r in resposta.json()), key=lambda r: r["id"])
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    destino = EVIDENCIAS / f"{args.nome}.json"
    destino.write_text(json.dumps(relatos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(relatos)} relatos gravados em tests/evidencias/{destino.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
