from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import STATUS_EM_ABERTO, PontoOnibus, Relato, agora
from ..schemas import Indicadores, PontoOnibusOut
from ..utils import haversine_m

router = APIRouter(tags=["painel"])

RAIO_PONTO_M = 60.0


@router.get("/indicadores", response_model=Indicadores, summary="Indicadores do painel")
def indicadores(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Relato)) or 0
    por_status = {s: n for s, n in db.execute(select(Relato.status, func.count()).group_by(Relato.status))}
    por_tipo = {t: n for t, n in db.execute(select(Relato.tipo, func.count()).group_by(Relato.tipo))}
    por_prioridade = {
        p: n
        for p, n in db.execute(
            select(Relato.prioridade, func.count()).where(Relato.prioridade.is_not(None)).group_by(Relato.prioridade)
        )
    }

    resolvidos = list(db.scalars(select(Relato).where(Relato.resolvido_em.is_not(None))))
    tempo_medio = None
    if resolvidos:
        dias = [(r.resolvido_em - r.criado_em).total_seconds() / 86400 for r in resolvidos]
        tempo_medio = round(sum(dias) / len(dias), 1)

    pontos = list(db.scalars(select(PontoOnibus)))
    ativos = list(db.scalars(select(Relato).where(Relato.status.in_(STATUS_EM_ABERTO))))
    com_obstaculo = sum(1 for p in pontos if any(haversine_m(p.lat, p.lon, r.lat, r.lon) <= RAIO_PONTO_M for r in ativos))

    aguardando = por_status.get("novo", 0)
    return Indicadores(
        total_relatos=total,
        aguardando_triagem=aguardando,
        triados_pela_automacao=total - aguardando,
        relatos_por_status=por_status,
        relatos_por_prioridade=por_prioridade,
        relatos_por_tipo=por_tipo,
        relatos_resolvidos=len(resolvidos),
        tempo_medio_resolucao_dias=tempo_medio,
        pontos_onibus_total=len(pontos),
        pontos_onibus_com_obstaculo_ativo=com_obstaculo,
        gerado_em=agora(),
    )


@router.get("/pontos", response_model=list[PontoOnibusOut], summary="Pontos de ônibus e obstáculos em aberto próximos")
def pontos(db: Session = Depends(get_db)):
    pontos = list(db.scalars(select(PontoOnibus)))
    ativos = list(db.scalars(select(Relato).where(Relato.status.in_(STATUS_EM_ABERTO))))
    saida = []
    for p in pontos:
        n = sum(1 for r in ativos if haversine_m(p.lat, p.lon, r.lat, r.lon) <= RAIO_PONTO_M)
        saida.append(PontoOnibusOut.model_validate(p, from_attributes=True).model_copy(update={"relatos_ativos": n}))
    return saida
