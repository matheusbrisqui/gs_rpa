"""Prepara um cenário de demonstração no MVP para a execução de ponta a ponta do robô.

Cria relatos novos que exercitam cada regra de decisão e grava um arquivo de retorno
da prefeitura na pasta de entrada. Todos os dados são fictícios.

Uso (com o MVP no ar):
    python tests/preparar_cenario.py [--api-url http://127.0.0.1:8000] [--retorno-invalido]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]

# (rótulo, corpo do relato). Coordenadas na região da Av. Paulista, em São Paulo.
RELATOS = [
    ("A: PCD junto ao ponto MASP -> prioridade alta (R1)",
     {"tipo": "degrau_sem_rampa", "lat": -23.56135, "lon": -46.65585, "perfil": "pcd",
      "descricao": "Guia alta em frente ao ponto, cadeira não sobe"}),
    ("B: mesmo obstáculo a ~6 m de A -> duplicado de A (mesmo lote)",
     {"tipo": "degrau_sem_rampa", "lat": -23.56140, "lon": -46.65583, "perfil": "outro",
      "descricao": "Sem rampa no ponto de ônibus"}),
    ("C: iluminação a ~8 m de um relato já encaminhado (Praça da Sé) -> duplicado",
     {"tipo": "iluminacao", "lat": -23.55046, "lon": -46.63406, "perfil": "idoso",
      "descricao": "Ponto de ônibus escuro"}),
    ("D: coordenada fora de São Paulo -> inválido",
     {"tipo": "entulho_lixo", "lat": 0.0, "lon": 0.0, "perfil": "outro",
      "descricao": "Relato enviado sem GPS"}),
    ("E: idoso longe de ponto de ônibus -> prioridade média (R2)",
     {"tipo": "iluminacao", "lat": -23.57250, "lon": -46.64150, "perfil": "idoso",
      "descricao": "Rua escura à noite"}),
    ("F: sem perfil prioritário e longe de ponto -> prioridade normal (R3)",
     {"tipo": "entulho_lixo", "lat": -23.57400, "lon": -46.63900, "perfil": "outro",
      "descricao": "Entulho de obra na calçada"}),
]

# Protocolos dos dados de demonstração do MVP (mvp/app/seed.py)
RETORNO_VALIDO = (
    "protocolo;situacao;data_conclusao\n"
    "SP156-2026-000101;CONCLUIDO;{ontem}\n"      # relato de buraco encaminhado -> resolvido
    "SP156-2026-000095;EM_ANDAMENTO;\n"          # sem alteração
    "SP156-2026-000110;INDEFERIDO;\n"            # requer revisão humana
    "SP156-2026-999999;CONCLUIDO;{ontem}\n"      # protocolo que não existe no MVP
    "SP156-2026-000095;FECHADO;{ontem}\n"        # linha com situação desconhecida
)
RETORNO_INVALIDO = "id,status\n1,ok\n"           # cabeçalho errado: arquivo inteiro é rejeitado


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--retorno-invalido", action="store_true", help="grava também um arquivo de retorno corrompido")
    parser.add_argument("--entrada", default=str(RAIZ / "entrada"))
    args = parser.parse_args()

    try:
        with httpx.Client(base_url=args.api_url, timeout=10) as http:
            http.get("/health").raise_for_status()
            for rotulo, corpo in RELATOS:
                resp = http.post("/relatos", json=corpo)
                resp.raise_for_status()
                print(f"relato #{resp.json()['id']:>3} criado  | {rotulo}")
    except httpx.HTTPError as exc:
        print(f"Não foi possível falar com o MVP em {args.api_url}: {type(exc).__name__}", file=sys.stderr)
        return 1

    entrada = Path(args.entrada)
    entrada.mkdir(parents=True, exist_ok=True)
    hoje, ontem = date.today(), date.today() - timedelta(days=1)
    arquivo = entrada / f"retorno_prefeitura_{hoje:%Y%m%d}.csv"
    arquivo.write_text(RETORNO_VALIDO.format(ontem=ontem.isoformat()), encoding="utf-8")
    print(f"arquivo de retorno gravado em {arquivo.relative_to(RAIZ)}")
    if args.retorno_invalido:
        ruim = entrada / f"retorno_prefeitura_{hoje:%Y%m%d}_corrompido.csv"
        ruim.write_text(RETORNO_INVALIDO, encoding="utf-8")
        print(f"arquivo corrompido gravado em {ruim.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
