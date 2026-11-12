import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Relato, agora
from ..schemas import RelatoCreate, RelatoOut, RelatoUpdate
from ..utils import hash_usuario

router = APIRouter(prefix="/relatos", tags=["relatos"])


def exigir_token_automacao(x_automation_token: str | None = Header(default=None)) -> None:
    """Só a automação altera relatos. Sem AUTOMATION_TOKEN configurado, fica aberto (desenvolvimento)."""
    esperado = settings.automation_token
    if esperado and not secrets.compare_digest(x_automation_token or "", esperado):
        raise HTTPException(401, "Token de automação inválido ou ausente")


@router.get("", response_model=list[RelatoOut], summary="Lista relatos (usado pelas telas e pelo robô)")
def listar(
    status: str | None = Query(default=None, description="novo | validado | encaminhado | resolvido | invalido | duplicado"),
    tipo: str | None = None,
    protocolo: str | None = Query(default=None, description="localiza o relato de um protocolo"),
    limite: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
):
    stmt = select(Relato).order_by(Relato.criado_em.desc()).limit(limite)
    if status:
        stmt = stmt.where(Relato.status == status)
    if tipo:
        stmt = stmt.where(Relato.tipo == tipo)
    if protocolo:
        stmt = stmt.where(Relato.protocolo == protocolo)
    return list(db.scalars(stmt))


@router.post("", response_model=RelatoOut, status_code=201, summary="Cria relato (tela Relatar)")
def criar(dados: RelatoCreate, db: Session = Depends(get_db)):
    relato = Relato(
        tipo=dados.tipo,
        descricao=dados.descricao,
        lat=dados.lat,
        lon=dados.lon,
        usuario_hash=hash_usuario(dados.identificador_usuario),  # LGPD: identificador nunca é persistido
        perfil=dados.perfil,
        fonte="app",
        status="novo",  # todo relato nasce "novo" e espera a triagem do robô
    )
    db.add(relato)
    db.commit()
    db.refresh(relato)
    return relato


@router.get("/{relato_id}", response_model=RelatoOut)
def obter(relato_id: int, db: Session = Depends(get_db)):
    relato = db.get(Relato, relato_id)
    if not relato:
        raise HTTPException(404, "Relato não encontrado")
    return relato


@router.patch(
    "/{relato_id}",
    response_model=RelatoOut,
    summary="Atualiza status, prioridade, protocolo e referência ao original (robô)",
    dependencies=[Depends(exigir_token_automacao)],
)
def atualizar(relato_id: int, dados: RelatoUpdate, db: Session = Depends(get_db)):
    relato = db.get(Relato, relato_id)
    if not relato:
        raise HTTPException(404, "Relato não encontrado")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(relato, campo, valor)
    if dados.status == "resolvido" and relato.resolvido_em is None:
        relato.resolvido_em = agora()
    relato.atualizado_em = agora()
    db.commit()
    db.refresh(relato)
    return relato
