"""Leitura do arquivo de retorno da prefeitura: linhas boas, linhas ruins e arquivo inaproveitável."""

from datetime import date

import pytest

from passo_livre_rpa import retorno_prefeitura as rp


def escrever(tmp_path, conteudo, nome="retorno_prefeitura_20261110.csv", encoding="utf-8"):
    caminho = tmp_path / nome
    caminho.write_bytes(conteudo.encode(encoding))
    return caminho


def test_le_linhas_validas_e_aponta_as_invalidas(tmp_path):
    arquivo = escrever(
        tmp_path,
        "protocolo;situacao;data_conclusao\n"
        "PL-1;CONCLUIDO;2026-11-09\n"
        "PL-2;em_andamento;\n"
        "PL-3;INDEFERIDO;\n"
        "\n"
        "PL-4;FECHADO;2026-11-09\n"          # situação desconhecida
        "PL-5;CONCLUIDO;\n"                  # concluído sem data
        "PL-1;CONCLUIDO;2026-11-09\n"        # protocolo repetido
        "PL-6;CONCLUIDO;09/11/2026\n"        # data fora do padrão
        "PL-7;CONCLUIDO\n",                  # coluna faltando
    )
    validas, problemas = rp.ler(arquivo)
    assert [(v.protocolo, v.situacao, v.data_conclusao) for v in validas] == [
        ("PL-1", "CONCLUIDO", date(2026, 11, 9)),
        ("PL-2", "EM_ANDAMENTO", None),
        ("PL-3", "INDEFERIDO", None),
    ]
    assert len(problemas) == 5
    assert problemas[0].startswith("linha 6:") and "FECHADO" in problemas[0]


def test_aceita_arquivo_salvo_pelo_excel_com_bom(tmp_path):
    arquivo = escrever(tmp_path, "protocolo;situacao;data_conclusao\nPL-1;CONCLUIDO;2026-11-09\n", encoding="utf-8-sig")
    validas, problemas = rp.ler(arquivo)
    assert len(validas) == 1 and problemas == []


@pytest.mark.parametrize(
    "conteudo, encoding, trecho",
    [
        ("", "utf-8", "vazio"),
        ("id,status\n1,ok\n", "utf-8", "cabeçalho inesperado"),
        ("protocolo;situação;data_conclusão\nPL-1;CONCLUÍDO;\n", "latin-1", "UTF-8"),
    ],
)
def test_arquivo_inaproveitavel_levanta_erro(tmp_path, conteudo, encoding, trecho):
    arquivo = escrever(tmp_path, conteudo, encoding=encoding)
    with pytest.raises(rp.ArquivoInvalido, match=trecho):
        rp.ler(arquivo)


def test_localiza_somente_arquivos_de_retorno(tmp_path):
    escrever(tmp_path, "x", nome="retorno_prefeitura_20261109.csv")
    escrever(tmp_path, "x", nome="retorno_prefeitura_20261110.csv")
    escrever(tmp_path, "x", nome="outra_coisa.csv")
    assert [p.name for p in rp.localizar(tmp_path)] == ["retorno_prefeitura_20261109.csv", "retorno_prefeitura_20261110.csv"]
