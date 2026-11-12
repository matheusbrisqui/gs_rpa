"""Cenários de DECISÃO: as regras de negócio isoladas."""

from conftest import AGORA, LONGE_DE_PONTO, PONTO_MASP, relato

from passo_livre_rpa import regras
from passo_livre_rpa.config import AREA_SAO_PAULO


def test_distancia_entre_dois_pontos_da_paulista():
    # MASP até a esquina da Consolação: cerca de 630 m em linha reta
    d = regras.distancia_m(-23.56135, -46.65585, -23.55740, -46.66030)
    assert 600 < d < 660


# ---- validação ---------------------------------------------------------------
def test_relato_valido_nao_tem_motivos():
    assert regras.validar(relato(1), AREA_SAO_PAULO, AGORA) == []


def test_relato_fora_de_sao_paulo_e_invalido():
    assert regras.validar(relato(1, lat=0.0, lon=0.0), AREA_SAO_PAULO, AGORA) == ["fora_da_area_atendida"]


def test_relato_com_tipo_desconhecido_e_data_futura():
    r = relato(1, tipo="ovni", criado_em="2027-01-01T00:00:00")
    assert regras.validar(r, AREA_SAO_PAULO, AGORA) == ["tipo_desconhecido", "data_no_futuro"]


def test_relato_sem_coordenada_ou_data():
    r = relato(1, lat=None, criado_em="ontem")
    assert regras.validar(r, AREA_SAO_PAULO, AGORA) == ["coordenada_ausente", "data_invalida"]


# ---- duplicidade -------------------------------------------------------------
def test_duplicado_quando_mesmo_tipo_dentro_do_raio():
    aberto = relato(10, status="encaminhado", criado_em="2026-11-05T10:00:00")
    novo = relato(11, lat=PONTO_MASP["lat"] + 0.00008)  # ~9 m ao norte
    achado = regras.encontrar_duplicado(novo, [aberto], 20, 30, AGORA)
    assert achado is not None and achado[0] == 10 and 8 < achado[1] < 10


def test_nao_duplica_fora_do_raio_tipo_diferente_ou_antigo():
    novo = relato(11)
    longe = relato(10, status="encaminhado", lat=PONTO_MASP["lat"] + 0.0005)  # ~55 m
    outro_tipo = relato(12, status="encaminhado", tipo="entulho_lixo")
    antigo = relato(13, status="encaminhado", criado_em="2026-09-01T10:00:00")  # mais de 30 dias
    assert regras.encontrar_duplicado(novo, [longe, outro_tipo, antigo], 20, 30, AGORA) is None


def test_duplicado_escolhe_o_mais_proximo():
    novo = relato(11)
    a = relato(10, status="encaminhado", lat=PONTO_MASP["lat"] + 0.00012)  # ~13 m
    b = relato(12, status="validado", lat=PONTO_MASP["lat"] + 0.00004)  # ~4 m
    assert regras.encontrar_duplicado(novo, [a, b], 20, 30, AGORA)[0] == 12


# ---- prioridade --------------------------------------------------------------
def test_prioridade_alta_perfil_prioritario_junto_ao_ponto():
    assert regras.definir_prioridade("pcd", 12.0, 60) == ("alta", "R1")
    assert regras.definir_prioridade("idoso", 60.0, 60) == ("alta", "R1")


def test_prioridade_media_so_perfil_ou_so_ponto():
    assert regras.definir_prioridade("pcd", 400.0, 60) == ("media", "R2")
    assert regras.definir_prioridade("outro", 30.0, 60) == ("media", "R2")
    assert regras.definir_prioridade("idoso", None, 60) == ("media", "R2")


def test_prioridade_normal_nos_demais_casos():
    assert regras.definir_prioridade("outro", 400.0, 60) == ("normal", "R3")
    assert regras.definir_prioridade("responsavel_carrinho", None, 60) == ("normal", "R3")


def test_ponto_mais_proximo_e_protocolo():
    r = relato(7, lat=LONGE_DE_PONTO[0], lon=LONGE_DE_PONTO[1])
    ponto, d = regras.ponto_mais_proximo(r, [PONTO_MASP])
    assert ponto["codigo"] == "340015329" and d > 1000
    assert regras.ponto_mais_proximo(r, []) is None
    assert regras.gerar_protocolo(7, AGORA) == "PL-20261110-00007"
