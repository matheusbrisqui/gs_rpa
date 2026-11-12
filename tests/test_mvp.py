"""Testes do aplicativo (MVP) no que a automação depende: o contrato da API usada pelo robô."""

import os

os.environ["DATABASE_URL"] = "sqlite://"  # banco em memória para os testes
os.environ["SEED_DEMO"] = "true"
os.environ["AUTOMATION_TOKEN"] = ""  # ignora o token de um eventual .env local

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app import database

# Engine em memória compartilhada entre as sessões do teste
database.engine = database.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
database.SessionLocal.configure(bind=database.engine)

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_mvp_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_mvp_dados_de_demonstracao_carregados(client):
    assert len(client.get("/relatos").json()) >= 10
    assert len(client.get("/pontos").json()) >= 8


def test_mvp_relato_nasce_novo_e_sem_dado_pessoal(client):
    novo = {
        "tipo": "buraco",
        "descricao": "teste",
        "lat": -23.56,
        "lon": -46.65,
        "identificador_usuario": "maria@example.com",
        "perfil": "pcd",
    }
    r = client.post("/relatos", json=novo)
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["status"] == "novo"
    assert corpo["prioridade"] is None and corpo["protocolo"] is None
    assert corpo["usuario_hash"] and "maria" not in corpo["usuario_hash"]
    assert "identificador_usuario" not in corpo
    assert corpo["criado_em"].endswith(("Z", "+00:00"))  # data com fuso explícito


def test_mvp_filtro_de_relatos_novos_para_o_robo(client):
    novos = client.get("/relatos", params={"status": "novo"}).json()
    assert novos and all(x["status"] == "novo" for x in novos)


def test_mvp_robo_encaminha_e_resolve(client):
    alvo = client.post("/relatos", json={"tipo": "entulho_lixo", "lat": -23.57, "lon": -46.64}).json()["id"]
    r = client.patch(f"/relatos/{alvo}", json={"status": "encaminhado", "prioridade": "media", "protocolo": "PL-TESTE-9"})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["prioridade"], r.json()["protocolo"]) == ("encaminhado", "media", "PL-TESTE-9")
    assert r.json()["resolvido_em"] is None

    r = client.patch(f"/relatos/{alvo}", json={"status": "resolvido"})
    assert r.json()["status"] == "resolvido"
    assert r.json()["resolvido_em"] is not None
    assert r.json()["protocolo"] == "PL-TESTE-9"  # atualização parcial preserva o que não foi enviado


def test_mvp_robo_marca_duplicado_e_busca_por_protocolo(client):
    a = client.post("/relatos", json={"tipo": "buraco", "lat": -23.5, "lon": -46.6}).json()
    b = client.post("/relatos", json={"tipo": "buraco", "lat": -23.5, "lon": -46.6}).json()
    client.patch(f"/relatos/{a['id']}", json={"status": "encaminhado", "protocolo": "PL-TESTE-1"})
    r = client.patch(f"/relatos/{b['id']}", json={"status": "duplicado", "duplicado_de": a["id"]})
    assert r.status_code == 200
    assert r.json()["status"] == "duplicado"
    assert r.json()["duplicado_de"] == a["id"]

    achados = client.get("/relatos", params={"protocolo": "PL-TESTE-1"}).json()
    assert [x["id"] for x in achados] == [a["id"]]


def test_mvp_alteracao_exige_token_quando_configurado(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "automation_token", "segredo-de-teste")
    alvo = client.get("/relatos").json()[0]["id"]
    assert client.patch(f"/relatos/{alvo}", json={"prioridade": "alta"}).status_code == 401
    errado = client.patch(f"/relatos/{alvo}", json={"prioridade": "alta"}, headers={"X-Automation-Token": "errado"})
    assert errado.status_code == 401
    certo = client.patch(f"/relatos/{alvo}", json={"prioridade": "alta"}, headers={"X-Automation-Token": "segredo-de-teste"})
    assert certo.status_code == 200


def test_mvp_recusa_dados_fora_do_dominio(client):
    assert client.post("/relatos", json={"tipo": "ovni", "lat": 0, "lon": 0}).status_code == 422
    alvo = client.get("/relatos").json()[0]["id"]
    assert client.patch(f"/relatos/{alvo}", json={"status": "sumiu"}).status_code == 422
    assert client.patch("/relatos/999999", json={"status": "resolvido"}).status_code == 404


def test_mvp_indicadores_refletem_a_triagem(client):
    antes = client.get("/indicadores").json()
    assert antes["total_relatos"] == antes["aguardando_triagem"] + antes["triados_pela_automacao"]
    assert antes["relatos_resolvidos"] >= 3
    assert antes["tempo_medio_resolucao_dias"] is not None

    alvo = client.get("/relatos", params={"status": "novo"}).json()[0]["id"]
    client.patch(f"/relatos/{alvo}", json={"status": "encaminhado", "prioridade": "alta", "protocolo": "PL-TESTE-2"})
    depois = client.get("/indicadores").json()
    assert depois["aguardando_triagem"] == antes["aguardando_triagem"] - 1
    assert depois["relatos_por_prioridade"].get("alta", 0) == antes["relatos_por_prioridade"].get("alta", 0) + 1


def test_mvp_telas_servidas(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/html")
    assert "Passo Livre" in r.text and "painel-chamados" in r.text
    assert client.get("/static/app.js").status_code == 200
