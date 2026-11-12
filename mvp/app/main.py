"""Aplicativo Passo Livre, no recorte usado pela automação de RPA.

Telas: mapa de obstáculos, formulário de relato, acompanhamento dos chamados e painel.
O robô (src/passo_livre_rpa) lê e atualiza os relatos pela API definida aqui.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from .routers import painel, relatos
from .seed import popular_se_vazio

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.seed_demo:
        with SessionLocal() as db:
            popular_se_vazio(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "API do Passo Livre, CitizenTech de acessibilidade e mobilidade urbana. "
        "O aplicativo web registra relatos de obstáculos; a automação de RPA lê os relatos novos, "
        "decide o encaminhamento e grava status, prioridade e protocolo por esta API."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(relatos.router)
app.include_router(painel.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "servico": settings.app_name, "versao": app.version}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
