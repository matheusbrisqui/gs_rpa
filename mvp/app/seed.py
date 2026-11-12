"""Dados de demonstração. Todos fictícios.

Os pontos de ônibus são coordenadas aproximadas de paradas da região da Av. Paulista e do
Centro de São Paulo. Os relatos simulam o histórico do aplicativo: alguns ainda novos
(esperando o robô), outros já encaminhados ou resolvidos. Nenhum dado pessoal real.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import PontoOnibus, Relato, agora
from .utils import hash_usuario

PONTOS = [
    ("340015329", "Av. Paulista - MASP", "Av. Paulista, 1578", -23.56135, -46.65585, True),
    ("340015332", "Av. Paulista - Trianon", "Av. Paulista, 1900", -23.56198, -46.65538, None),
    ("340015340", "Av. Paulista - Consolação", "Av. Paulista, 2200", -23.55740, -46.66030, False),
    ("340015350", "Av. Paulista - Brigadeiro", "Av. Paulista, 500", -23.56800, -46.64820, True),
    ("340015360", "Praça da Sé", "Praça da Sé, s/n", -23.55030, -46.63390, None),
    ("340015370", "Praça da República", "Praça da República, s/n", -23.54350, -46.64250, False),
    ("340015380", "Av. Brigadeiro Luís Antônio - Bela Vista", "Av. Brig. Luís Antônio, 1200", -23.56220, -46.64600, None),
    ("340015390", "R. Augusta - Baixo Augusta", "R. Augusta, 1500", -23.55560, -46.66100, True),
]

RELATOS = [
    # (tipo, descricao, lat, lon, perfil, status, prioridade, protocolo, dias_atras, resolvido_apos_dias)
    ("buraco", "Buraco grande no meio da calçada, impossível passar de cadeira", -23.56150, -46.65610, "pcd", "encaminhado", "alta", "SP156-2026-000101", 6, None),
    ("carro_na_calcada", "Carro estacionado bloqueando toda a calçada em frente ao ponto", -23.56210, -46.65520, "idoso", "novo", None, None, 1, None),
    ("degrau_sem_rampa", "Guia sem rebaixamento na travessia", -23.55760, -46.66010, "pcd", "validado", "alta", None, 3, None),
    ("entulho_lixo", "Entulho de obra ocupando a calçada", -23.56790, -46.64850, "responsavel_carrinho", "resolvido", "media", "SP156-2026-000088", 12, 9),
    ("iluminacao", "Ponto de ônibus sem iluminação à noite", -23.55040, -46.63410, "idoso", "encaminhado", "media", "SP156-2026-000095", 8, None),
    ("poste_obstaculo", "Poste no meio da faixa livre, sobra menos de 80 cm", -23.54370, -46.64230, "pcd", "novo", None, None, 2, None),
    ("buraco", "Tampa de bueiro quebrada", -23.56240, -46.64580, "outro", "resolvido", "normal", "SP156-2026-000070", 20, 14),
    ("carro_na_calcada", "Motos estacionadas na calçada estreita", -23.55580, -46.66080, "outro", "encaminhado", "normal", "SP156-2026-000110", 4, None),
    ("degrau_sem_rampa", "Rampa com inclinação muito alta, perigosa", -23.56100, -46.65700, "pcd", "novo", None, None, 0, None),
    ("entulho_lixo", "Sacos de lixo acumulados bloqueando a passagem", -23.55020, -46.63350, "idoso", "resolvido", "normal", "SP156-2026-000080", 15, 13),
]


def popular_se_vazio(db: Session) -> bool:
    if db.scalar(select(func.count()).select_from(Relato)) or db.scalar(select(func.count()).select_from(PontoOnibus)):
        return False
    for codigo, nome, endereco, lat, lon, acessivel in PONTOS:
        db.add(PontoOnibus(codigo=codigo, nome=nome, endereco=endereco, lat=lat, lon=lon, acessivel=acessivel))
    for i, (tipo, desc, lat, lon, perfil, status, prio, proto, dias, res_dias) in enumerate(RELATOS):
        criado = agora() - timedelta(days=dias, hours=(i * 3) % 10 + 1)
        db.add(
            Relato(
                tipo=tipo,
                descricao=desc,
                lat=lat,
                lon=lon,
                perfil=perfil,
                fonte="app",
                status=status,
                prioridade=prio,
                protocolo=proto,
                usuario_hash=hash_usuario(f"cidadao-demo-{i}"),
                criado_em=criado,
                atualizado_em=criado,
                resolvido_em=(criado + timedelta(days=res_dias)) if res_dias is not None else None,
            )
        )
    db.commit()
    return True
