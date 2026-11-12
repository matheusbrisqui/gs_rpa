from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

TIPOS_OBSTACULO = [
    "buraco",
    "carro_na_calcada",
    "entulho_lixo",
    "poste_obstaculo",
    "degrau_sem_rampa",
    "iluminacao",
    "outro",
]
# novo: aguardando o robô. validado e encaminhado: em aberto. Os demais encerram o relato.
STATUS_RELATO = ["novo", "validado", "encaminhado", "resolvido", "invalido", "duplicado"]
STATUS_EM_ABERTO = ("novo", "validado", "encaminhado")
PRIORIDADES = ["alta", "media", "normal"]
PERFIS = ["pcd", "idoso", "responsavel_carrinho", "outro"]


def agora() -> datetime:
    return datetime.now(UTC)


class Relato(Base):
    __tablename__ = "relatos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    # LGPD: nunca guardamos e-mail/nome; só um hash salgado do identificador
    usuario_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    perfil: Mapped[str] = mapped_column(String(30), default="outro")
    fonte: Mapped[str] = mapped_column(String(20), default="app", index=True)
    status: Mapped[str] = mapped_column(String(20), default="novo", index=True)
    # Os três campos abaixo são preenchidos pelo robô
    prioridade: Mapped[str | None] = mapped_column(String(10), nullable=True)
    protocolo: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    duplicado_de: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PontoOnibus(Base):
    __tablename__ = "pontos_onibus"

    codigo: Mapped[str] = mapped_column(String(20), primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    endereco: Mapped[str | None] = mapped_column(String(300), nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    acessivel: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = não avaliado
