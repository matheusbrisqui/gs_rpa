from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from .models import PERFIS, PRIORIDADES, STATUS_RELATO, TIPOS_OBSTACULO

Tipo = Literal[tuple(TIPOS_OBSTACULO)]  # type: ignore[valid-type]
Status = Literal[tuple(STATUS_RELATO)]  # type: ignore[valid-type]
Prioridade = Literal[tuple(PRIORIDADES)]  # type: ignore[valid-type]
Perfil = Literal[tuple(PERFIS)]  # type: ignore[valid-type]

# O banco guarda as datas em UTC sem fuso. A API sempre devolve com o fuso explícito,
# para o navegador mostrar no horário local de quem está vendo.
DataUTC = Annotated[datetime, AfterValidator(lambda d: d if d.tzinfo else d.replace(tzinfo=UTC))]


class RelatoCreate(BaseModel):
    tipo: Tipo
    descricao: str | None = Field(default=None, max_length=1000)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    # identificador opcional (e-mail). É transformado em hash e descartado.
    identificador_usuario: str | None = Field(default=None, max_length=200)
    perfil: Perfil = "outro"


class RelatoUpdate(BaseModel):
    """Campos que a automação grava."""

    status: Status | None = None
    prioridade: Prioridade | None = None
    protocolo: str | None = Field(default=None, max_length=40)
    duplicado_de: int | None = None


class RelatoOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    tipo: str
    descricao: str | None
    lat: float
    lon: float
    usuario_hash: str | None
    perfil: str
    fonte: str
    status: str
    prioridade: str | None
    protocolo: str | None
    duplicado_de: int | None = None
    criado_em: DataUTC
    atualizado_em: DataUTC
    resolvido_em: DataUTC | None


class PontoOnibusOut(BaseModel):
    model_config = {"from_attributes": True}

    codigo: str
    nome: str
    endereco: str | None
    lat: float
    lon: float
    acessivel: bool | None
    relatos_ativos: int = 0


class Indicadores(BaseModel):
    total_relatos: int
    aguardando_triagem: int
    triados_pela_automacao: int
    relatos_por_status: dict[str, int]
    relatos_por_prioridade: dict[str, int]
    relatos_por_tipo: dict[str, int]
    relatos_resolvidos: int
    tempo_medio_resolucao_dias: float | None
    pontos_onibus_total: int
    pontos_onibus_com_obstaculo_ativo: int
    gerado_em: datetime
