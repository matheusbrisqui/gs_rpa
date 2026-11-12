"""Execução completa do robô contra uma API simulada: cenários de SUCESSO, DECISÃO e FALHA."""

import csv
import json

from conftest import AGORA, LONGE_DE_PONTO, PONTO_MASP, MvpFalso, agora, geocodificador, relato

from passo_livre_rpa import regras
from passo_livre_rpa.__main__ import main
from passo_livre_rpa.robo import executar


def rodar(config, mvp, geo=None, **kw):
    return executar(config, cliente=mvp.cliente(**kw), geocodificador=geo or geocodificador(), agora=agora, console=False)


def ler_chamados(config, resumo):
    with (config.saida_dir / resumo.arquivo_chamados).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def ler_logs(config):
    texto = "".join(p.read_text(encoding="utf-8") for p in sorted(config.logs_dir.glob("robo_*.log")))
    eventos = [
        json.loads(linha)
        for p in sorted(config.logs_dir.glob("auditoria_*.jsonl"))
        for linha in p.read_text(encoding="utf-8").splitlines()
    ]
    return texto, eventos


# =============================== SUCESSO =====================================
def test_sucesso_encaminha_gera_chamado_e_atualiza_mvp(config):
    mvp = MvpFalso([relato(1, perfil="pcd")])
    resumo = rodar(config, mvp)

    assert resumo.situacao == "sucesso" and resumo.codigo_saida == 0
    assert (resumo.relatos_lidos, resumo.encaminhados, resumo.falhas) == (1, 1, 0)
    protocolo = regras.gerar_protocolo(1, AGORA.astimezone())
    assert mvp.relatos[1]["status"] == "encaminhado"            # integração: o MVP passa a mostrar o novo status
    assert mvp.relatos[1]["prioridade"] == "alta"
    assert mvp.relatos[1]["protocolo"] == protocolo

    chamado = ler_chamados(config, resumo)[0]
    assert chamado["protocolo"] == protocolo and chamado["prioridade"] == "alta" and chamado["regra_prioridade"] == "R1"
    assert chamado["endereco"] == "Avenida Paulista, 1578 - Bela Vista"
    assert chamado["ponto_onibus_codigo"] == PONTO_MASP["codigo"] and chamado["distancia_ponto_m"] == "0"

    gravado = json.loads((config.logs_dir / f"resumo_{resumo.execucao}.json").read_text(encoding="utf-8"))
    assert gravado["encaminhados"] == 1 and gravado["situacao"] == "sucesso"
    assert not (config.logs_dir / ".robo.lock").exists()


def test_sucesso_sem_relatos_novos_nao_gera_arquivo(config):
    mvp = MvpFalso([relato(1, status="encaminhado")])
    resumo = rodar(config, mvp)
    assert resumo.situacao == "sucesso" and resumo.relatos_lidos == 0 and resumo.arquivo_chamados is None
    assert mvp.patches == 0


def test_sucesso_retorno_concluido_marca_relato_como_resolvido(config):
    (config.entrada_dir / "retorno_prefeitura_20261110.csv").write_text(
        "protocolo;situacao;data_conclusao\nPL-A;CONCLUIDO;2026-11-09\nPL-B;EM_ANDAMENTO;\n", encoding="utf-8"
    )
    mvp = MvpFalso([relato(1, status="encaminhado", protocolo="PL-A"), relato(2, status="encaminhado", protocolo="PL-B")])
    resumo = rodar(config, mvp)

    assert resumo.retorno_arquivos_lidos == 1 and resumo.retorno_resolvidos == 1
    assert mvp.relatos[1]["status"] == "resolvido" and mvp.relatos[2]["status"] == "encaminhado"
    assert not list(config.entrada_dir.glob("*.csv"))                      # saiu da entrada...
    assert (config.entrada_dir / "processados" / "retorno_prefeitura_20261110.csv").exists()  # ...para processados


def test_reexecucao_nao_processa_duas_vezes(config):
    mvp = MvpFalso([relato(1), relato(2, tipo="entulho_lixo")])
    primeira = rodar(config, mvp)
    patches = mvp.patches
    segunda = rodar(config, mvp)
    assert primeira.encaminhados == 2
    assert segunda.relatos_lidos == 0 and segunda.encaminhados == 0 and mvp.patches == patches


def test_token_de_automacao_e_enviado(config):
    mvp = MvpFalso([relato(1)])
    mvp.token_esperado = "segredo"
    assert rodar(config, mvp, token="segredo").encaminhados == 1



def test_falha_token_recusado_aborta_na_primeira_recusa(config):
    mvp = MvpFalso([relato(1), relato(2, tipo="entulho_lixo"), relato(3, tipo="iluminacao")])
    mvp.token_esperado = "segredo"
    resumo = rodar(config, mvp, token="errado")
    assert resumo.situacao == "abortado" and resumo.codigo_saida == 2 and resumo.encaminhados == 0
    assert "AUTOMATION_TOKEN" in resumo.erros[0]
    assert sum(1 for metodo, _ in mvp.chamadas if metodo == "PATCH") == 1   # não insistiu nos outros relatos
    assert all(r["status"] == "novo" for r in mvp.relatos.values())


# =============================== DECISÃO =====================================
def test_decisao_tres_niveis_de_prioridade_no_mesmo_lote(config):
    lat, lon = LONGE_DE_PONTO
    mvp = MvpFalso([
        relato(1, perfil="pcd", tipo="buraco"),                                   # perfil + ponto  -> alta
        relato(2, perfil="outro", tipo="entulho_lixo"),                           # só ponto        -> média
        relato(3, perfil="idoso", tipo="iluminacao", lat=lat, lon=lon),           # só perfil       -> média
        relato(4, perfil="outro", tipo="poste_obstaculo", lat=lat, lon=lon),      # nenhum          -> normal
    ])
    resumo = rodar(config, mvp)
    assert resumo.prioridades == {"alta": 1, "media": 2, "normal": 1}
    assert [mvp.relatos[i]["prioridade"] for i in (1, 2, 3, 4)] == ["alta", "media", "media", "normal"]
    chamados = {int(c["relato_id"]): c for c in ler_chamados(config, resumo)}
    assert chamados[4]["ponto_onibus_codigo"] == "" and chamados[4]["regra_prioridade"] == "R3"


def test_decisao_duplicado_de_relato_ja_encaminhado(config):
    mvp = MvpFalso([
        relato(10, status="encaminhado", protocolo="PL-ANTIGO", criado_em="2026-11-05T10:00:00"),
        relato(11, lat=PONTO_MASP["lat"] + 0.00008),
    ])
    resumo = rodar(config, mvp)
    assert (resumo.duplicados, resumo.encaminhados) == (1, 0)
    assert mvp.relatos[11]["status"] == "duplicado" and mvp.relatos[11]["duplicado_de"] == 10
    assert resumo.arquivo_chamados is None                    # duplicado não gera novo chamado


def test_decisao_duplicado_dentro_do_mesmo_lote(config):
    mvp = MvpFalso([
        relato(1, criado_em="2026-11-10T09:00:00"),
        relato(2, criado_em="2026-11-10T09:05:00", lat=PONTO_MASP["lat"] + 0.00005),
    ])
    resumo = rodar(config, mvp)
    assert (resumo.encaminhados, resumo.duplicados) == (1, 1)
    assert mvp.relatos[1]["status"] == "encaminhado"           # o mais antigo segue
    assert mvp.relatos[2]["duplicado_de"] == 1                 # o mais novo aponta para ele


def test_decisao_relato_invalido_e_marcado_e_nao_encaminhado(config):
    mvp = MvpFalso([relato(1, lat=0.0, lon=0.0), relato(2)])
    resumo = rodar(config, mvp)
    assert (resumo.invalidos, resumo.encaminhados) == (1, 1)
    assert mvp.relatos[1]["status"] == "invalido" and mvp.relatos[2]["status"] == "encaminhado"


def test_decisao_retorno_indeferido_e_sem_relato_nao_alteram_o_mvp(config):
    (config.entrada_dir / "retorno_prefeitura_20261110.csv").write_text(
        "protocolo;situacao;data_conclusao\nPL-A;INDEFERIDO;\nPL-NAO-EXISTE;CONCLUIDO;2026-11-09\n", encoding="utf-8"
    )
    mvp = MvpFalso([relato(1, status="encaminhado", protocolo="PL-A")])
    resumo = rodar(config, mvp)
    assert (resumo.retorno_indeferidos, resumo.retorno_sem_relato, resumo.retorno_resolvidos) == (1, 1, 0)
    assert mvp.relatos[1]["status"] == "encaminhado" and mvp.patches == 0


# ================================ FALHA ======================================
def test_falha_api_fora_do_ar_aborta_e_registra(config):
    mvp = MvpFalso([relato(1)])
    mvp.fora_do_ar = True
    resumo = rodar(config, mvp)

    assert resumo.situacao == "abortado" and resumo.codigo_saida == 2
    assert "após 3 tentativa(s)" in resumo.erros[0]
    assert mvp.chamadas == [("GET", "/health")] * 3            # tentou 3 vezes e parou
    texto, eventos = ler_logs(config)
    assert "ERROR" in texto and "Execução abortada" in texto
    assert eventos[-1]["resultado"] == "abortada"
    assert not (config.logs_dir / ".robo.lock").exists()       # trava liberada mesmo com erro


def test_falha_em_um_item_nao_interrompe_o_lote(config):
    mvp = MvpFalso([relato(1), relato(2, tipo="entulho_lixo"), relato(3, tipo="iluminacao")])
    mvp.patch_erro_422 = {2}
    resumo = rodar(config, mvp)
    assert resumo.situacao == "sucesso_com_falhas" and resumo.codigo_saida == 1
    assert (resumo.encaminhados, resumo.falhas) == (2, 1)
    assert mvp.relatos[2]["status"] == "novo"                  # volta na próxima execução
    assert [c["relato_id"] for c in ler_chamados(config, resumo)] == ["1", "3"]


def test_falha_erro_500_e_repetido_antes_de_desistir(config):
    mvp = MvpFalso([relato(1)])
    mvp.patch_erro_500 = {1}
    resumo = rodar(config, mvp)
    assert resumo.falhas == 1 and mvp.chamadas.count(("PATCH", "/relatos/1")) == 3


def test_falha_api_cai_no_meio_do_lote(config):
    tipos = ["buraco", "entulho_lixo", "iluminacao", "outro", "poste_obstaculo"]
    mvp = MvpFalso([relato(i, tipo=t) for i, t in enumerate(tipos, start=1)])
    mvp.cair_depois_de_patches = 1
    resumo = rodar(config, mvp, tentativas=1)
    assert resumo.situacao == "abortado" and resumo.encaminhados == 1 and resumo.falhas == 2
    assert "não processado(s)" in resumo.erros[0]
    assert [mvp.relatos[i]["status"] for i in (1, 2, 3, 4, 5)] == ["encaminhado", "novo", "novo", "novo", "novo"]
    # o que foi encaminhado antes da queda continua rastreável pelo resumo
    assert resumo.arquivo_chamados == f"chamados_{resumo.execucao}.csv"
    assert [c["relato_id"] for c in ler_chamados(config, resumo)] == ["1"]


def test_falha_arquivo_de_retorno_invalido_vai_para_rejeitados(config):
    (config.entrada_dir / "retorno_prefeitura_20261110.csv").write_text("id,status\n1,ok\n", encoding="utf-8")
    mvp = MvpFalso([relato(1)])
    resumo = rodar(config, mvp)
    assert resumo.retorno_arquivos_rejeitados == 1 and resumo.situacao == "sucesso_com_falhas"
    assert (config.entrada_dir / "rejeitados" / "retorno_prefeitura_20261110.csv").exists()
    assert resumo.encaminhados == 1                            # a triagem seguiu normalmente


def test_falha_linhas_ruins_no_retorno_sao_contadas(config):
    (config.entrada_dir / "retorno_prefeitura_20261110.csv").write_text(
        "protocolo;situacao;data_conclusao\nPL-A;FECHADO;\nPL-A;CONCLUIDO;2026-11-09\n", encoding="utf-8"
    )
    mvp = MvpFalso([relato(1, status="encaminhado", protocolo="PL-A")])
    resumo = rodar(config, mvp)
    assert resumo.retorno_linhas_invalidas == 1 and resumo.retorno_resolvidos == 1


def test_falha_pasta_de_entrada_ausente_nao_e_erro(config):
    config.entrada_dir.rmdir()
    resumo = rodar(config, MvpFalso([relato(1)]))
    assert resumo.situacao == "sucesso" and resumo.encaminhados == 1


def test_falha_geocodificador_fora_segue_sem_endereco(config):
    mvp = MvpFalso([relato(i, tipo=t) for i, t in enumerate(["buraco", "entulho_lixo", "iluminacao", "outro"], start=1)])
    geo = geocodificador(falhar=True)
    resumo = rodar(config, mvp, geo=geo)
    assert resumo.situacao == "sucesso" and resumo.encaminhados == 4 and resumo.sem_endereco == 4
    assert geo.falhas == 3 and geo.ativo is False              # desligou depois de 3 falhas seguidas
    assert all(c["endereco"] == "" for c in ler_chamados(config, resumo))


def test_falha_ao_gravar_chamado_desfaz_a_atualizacao(config):
    config.saida_dir.write_text("isto é um arquivo, não uma pasta", encoding="utf-8")
    mvp = MvpFalso([relato(1)])
    resumo = rodar(config, mvp)
    assert resumo.falhas == 1 and resumo.encaminhados == 0
    assert mvp.relatos[1]["status"] == "novo" and mvp.relatos[1]["protocolo"] is None


def test_falha_execucao_simultanea_e_bloqueada(config):
    config.logs_dir.mkdir()
    (config.logs_dir / ".robo.lock").write_text("123")
    mvp = MvpFalso([relato(1)])
    resumo = rodar(config, mvp)
    assert resumo.situacao == "ja_em_execucao" and resumo.codigo_saida == 3 and mvp.chamadas == []


# ============================== AUDITORIA / LGPD ==============================
def test_logs_tem_data_itens_e_nao_expoem_dados_do_cidadao(config):
    mvp = MvpFalso([relato(1, perfil="pcd"), relato(2, lat=0.0, lon=0.0), relato(3, lat=PONTO_MASP["lat"] + 0.00005)])
    resumo = rodar(config, mvp)
    texto, eventos = ler_logs(config)

    assert "2026-" in texto and resumo.execucao in texto
    assert {e["resultado"] for e in eventos} == {"encaminhado", "invalido", "duplicado"}
    assert all({"quando", "execucao", "etapa", "resultado"} <= e.keys() for e in eventos)

    tudo = texto + json.dumps(eventos) + (config.saida_dir / resumo.arquivo_chamados).read_text(encoding="utf-8-sig")
    for proibido in ("TEXTO-LIVRE-DO-CIDADAO", "HASH-DO-CIDADAO", "pcd", "perfil"):
        assert proibido not in tudo


def test_linha_de_comando_devolve_codigo_de_saida(config, monkeypatch, tmp_path):
    monkeypatch.setenv("PASSOLIVRE_API_URL", "http://127.0.0.1:9")   # porta sem serviço
    monkeypatch.setenv("RPA_LOGS_DIR", str(tmp_path / "logs-cli"))
    monkeypatch.setenv("RPA_ENTRADA_DIR", str(tmp_path / "entrada-cli"))
    monkeypatch.setenv("RPA_HTTP_TENTATIVAS", "1")
    monkeypatch.setenv("RPA_HTTP_TIMEOUT_S", "2")
    assert main(["--silencioso", "--sem-geocodificacao"]) == 2
