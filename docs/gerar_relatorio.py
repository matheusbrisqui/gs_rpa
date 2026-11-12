"""Gera o Relatório Técnico em PDF da disciplina de RPA (`docs/relatorio_tecnico_rpa.pdf`).

O texto fica neste arquivo; as evidências são lidas dos artefatos reais da última
demonstração (logs/, tests/evidencias/, assets/) e os dados da equipe vêm de
`docs/equipe.json`. Campos não preenchidos saem em vermelho. O mesmo comando atualiza
no README o bloco de integrantes e links.

Uso:  python docs/gerar_relatorio.py
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

RPA = Path(__file__).resolve().parents[1]  # raiz do repositório
SAIDA = RPA / "docs" / "relatorio_tecnico_rpa.pdf"
LARGURA_UTIL = A4[0] - 4 * cm

AZUL = colors.HexColor("#0b57d0")
CINZA = colors.HexColor("#f1f4f8")
BORDA = colors.HexColor("#c9d1dc")

base = getSampleStyleSheet()
E_TITULO = ParagraphStyle("titulo", parent=base["Title"], fontSize=22, leading=27, textColor=AZUL, spaceAfter=6)
E_SUB = ParagraphStyle("sub", parent=base["Normal"], fontSize=12, leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#334155"))
E_H1 = ParagraphStyle("h1", parent=base["Heading1"], fontSize=14, leading=18, textColor=AZUL, spaceBefore=14, spaceAfter=6)
E_H2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=11, leading=14, spaceBefore=8, spaceAfter=4)
E_P = ParagraphStyle("p", parent=base["Normal"], fontSize=10, leading=14, spaceAfter=6)
E_CEL = ParagraphStyle("cel", parent=base["Normal"], fontSize=8.5, leading=11)
E_CELB = ParagraphStyle("celb", parent=E_CEL, fontName="Helvetica-Bold")
E_MONO = ParagraphStyle("mono", parent=base["Normal"], fontName="Courier", fontSize=6.3, leading=8.2, backColor=CINZA, borderPadding=4, spaceAfter=8)
E_LEG = ParagraphStyle("leg", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=8)


def p(texto: str, estilo=E_P) -> Paragraph:
    return Paragraph(texto, estilo)


def falta(o_que: str) -> str:
    return f'<font color="#b3261e"><b>[PREENCHER: {escape(o_que)}]</b></font>'


def ou_falta(valor: str | None, o_que: str) -> str:
    return escape(valor) if valor else falta(o_que)


def tabela(linhas: list[list], larguras: list[float], cabecalho: bool = True) -> Table:
    dados = [[c if not isinstance(c, str) else Paragraph(c, E_CELB if (cabecalho and i == 0) else E_CEL) for c in linha] for i, linha in enumerate(linhas)]
    t = Table(dados, colWidths=[w * LARGURA_UTIL for w in larguras], repeatRows=1 if cabecalho else 0)
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.4, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if cabecalho:
        estilo.append(("BACKGROUND", (0, 0), (-1, 0), CINZA))
    t.setStyle(TableStyle(estilo))
    return t


def mono(linhas: list[str], limite: int = 230) -> Paragraph:
    corpo = "<br/>".join(escape(linha if len(linha) <= limite else linha[: limite - 3] + "...").replace(" ", "&nbsp;") for linha in linhas)
    return Paragraph(corpo or "(sem registros)", E_MONO)


def imagem(caminho: Path, largura: float) -> Image | Paragraph:
    if not caminho.is_file():
        return p(falta(f"imagem {caminho.name}"))
    img = Image(str(caminho))
    proporcao = img.imageHeight / img.imageWidth
    img.drawWidth, img.drawHeight = largura, largura * proporcao
    return img


# ----------------------------------------------------------------- evidências
def carregar_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def carregar_resumos() -> list[dict]:
    return [carregar_json(arq, {}) for arq in sorted((RPA / "logs").glob("resumo_*.json"))]


def linhas_do_log(execucao: str) -> list[str]:
    saida = []
    for arq in sorted((RPA / "logs").glob("robo_*.log")):
        saida += [linha for linha in arq.read_text(encoding="utf-8").splitlines() if f"| {execucao} |" in linha]
    return saida


def eventos_de_auditoria(execucao: str) -> list[str]:
    saida = []
    for arq in sorted((RPA / "logs").glob("auditoria_*.jsonl")):
        saida += [linha for linha in arq.read_text(encoding="utf-8").splitlines() if f'"execucao": "{execucao}"' in linha]
    return saida


def descrever(resumo: dict) -> str:
    erros = " ".join(resumo.get("erros", []))
    if resumo.get("situacao") == "abortado" and "token" in erros.lower():
        return "Credencial recusada: aborta na primeira recusa, nada é alterado"
    if resumo.get("situacao") == "abortado":
        return "API do MVP fora do ar: 3 tentativas, registro do erro e encerramento"
    if resumo.get("relatos_lidos", 0) == 0:
        return "Reexecução sem pendências: nada é processado duas vezes"
    if resumo.get("falhas") and not resumo.get("encaminhados"):
        return "Falha isolada em um relato: registrada, relato mantido como novo"
    if resumo.get("relatos_lidos", 0) >= 5:
        return "Execução completa: retorno da prefeitura, validação, duplicidade e prioridades"
    return "Recuperação: relato pendente da falha anterior é processado"


def rodar_testes() -> tuple[str, dict[str, list[str]]]:
    """Executa a suíte e devolve (linha de resultado, testes por categoria)."""
    comando = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    resultado = subprocess.run(comando, cwd=RPA, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ultima = [linha for linha in resultado.stdout.splitlines() if linha.strip()][-1:] or ["suíte não executada"]
    coleta = subprocess.run([*comando, "--collect-only"], cwd=RPA, capture_output=True, text=True, encoding="utf-8", errors="replace")
    categorias: dict[str, list[str]] = {"Sucesso": [], "Decisão": [], "Falha": [], "Auditoria, LGPD e apoio": [], "API do aplicativo (integração)": []}
    for linha in coleta.stdout.splitlines():
        if "::" not in linha:
            continue
        arquivo, nome = linha.split("::", 1)
        nome = re.sub(r"\[.*\]$", "", nome)
        if "test_mvp" in arquivo:
            chave = "API do aplicativo (integração)"
        elif nome.startswith("test_sucesso"):
            chave = "Sucesso"
        elif nome.startswith("test_falha") or "inaproveitavel" in nome:
            chave = "Falha"
        elif nome.startswith("test_decisao") or "test_regras" in arquivo:
            chave = "Decisão"
        else:
            chave = "Auditoria, LGPD e apoio"
        if nome not in categorias[chave]:
            categorias[chave].append(nome)
    return ultima[0].strip("= "), categorias


# ----------------------------------------------------------------- documento
def rodape(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(2 * cm, 1.2 * cm, "Passo Livre | Relatório Técnico de RPA | FIAP Global Solution 2026.2")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def montar() -> list:
    equipe = carregar_json(RPA / "docs" / "equipe.json", {})
    integrantes = [i for i in equipe.get("integrantes", []) if i.get("nome") or i.get("rm")]
    repositorio = equipe.get("repositorio") or ""
    video = equipe.get("video") or ""
    resumos = carregar_resumos()
    # A execução detalhada no relatório é a maior entre as que têm o lote guardado em tests/evidencias/
    com_evidencia = [r for r in resumos if (RPA / "tests" / "evidencias" / (r.get("arquivo_chamados") or "-")).is_file()]
    principal = max(com_evidencia or resumos, key=lambda r: r.get("relatos_lidos", 0), default={})
    fora_do_ar = next((r for r in resumos if r.get("situacao") == "abortado" and "token" not in " ".join(r.get("erros", [])).lower()), {})
    recusada = next((r for r in resumos if r.get("situacao") == "abortado" and "token" in " ".join(r.get("erros", [])).lower()), {})
    resultado_testes, categorias = rodar_testes()

    h = []
    # ---- capa
    h += [Spacer(1, 3.5 * cm), p("Relatório Técnico", E_TITULO), p("Robotic Process Automation", E_SUB),
          p("Do Processo Manual à Automação Inteligente", E_SUB), Spacer(1, 1.2 * cm),
          p("<b>Passo Livre</b>: do relato ao chamado", ParagraphStyle("c1", parent=E_SUB, fontSize=16, leading=20)),
          p("CitizenTech de acessibilidade e mobilidade urbana", E_SUB), Spacer(1, 1.5 * cm),
          p("FIAP | Global Solution 2026.2 | Engenharia de Software | 4º ano | Turma 4ES", E_SUB),
          p("Professores: Bruno Diniz e Cibele Ribeiro", E_SUB), p(f"{date.today():%d/%m/%Y}", E_SUB), PageBreak()]

    # ---- 1
    h.append(p("1. Integrantes", E_H1))
    linhas = [["Nome completo", "RM"]] + ([[escape(i.get("nome") or ""), escape(i.get("rm") or "")] for i in integrantes] or [[falta("nome completo de cada integrante em docs/equipe.json"), falta("RM")]])
    h.append(tabela(linhas, [0.75, 0.25]))

    # ---- 2
    h.append(p("2. Identificação da CitizenTech e problema resolvido", E_H1))
    h.append(p("<b>Passo Livre</b> é um mapa colaborativo de obstáculos em calçadas e pontos de ônibus de São Paulo, voltado a pessoas com "
               "deficiência, idosos e responsáveis com carrinho. O cidadão fotografa ou relata o obstáculo, o mapa e a rota acessível se "
               "atualizam e os relatos são encaminhados ao poder público. Este repositório traz o recorte do produto usado pela automação: "
               "o aplicativo web (mapa, formulário de relato, acompanhamento dos chamados e painel), sua API e o robô."))
    h.append(p("<b>Problema do cidadão:</b> quem tem mobilidade reduzida não consegue saber se o trajeto até o ponto de ônibus é acessível, "
               "e os obstáculos que relata demoram a ser resolvidos."))
    h.append(p("<b>Problema operacional que a automação resolve:</b> sem automação, cada relato recebido pelo aplicativo dependeria de uma "
               "pessoa para conferir os dados, verificar se o problema já foi relatado, decidir a urgência, localizar o endereço, registrar o "
               "chamado no canal da prefeitura, anotar o protocolo e, dias depois, consultar o andamento e atualizar o aplicativo. É trabalho "
               "repetitivo, sujeito a erro e que atrasa justamente os casos mais urgentes."))

    # ---- 3
    h.append(p("3. Objetivo da automação e benefício para o cidadão", E_H1))
    h.append(p("Automatizar de ponta a ponta a <b>triagem e o encaminhamento dos relatos</b> e o <b>acompanhamento do retorno da prefeitura</b>, "
               "sem intervenção humana no fluxo normal, com regras de negócio explícitas, tratamento de exceções, trilha de auditoria e "
               "resultado visível no MVP."))
    h.append(tabela([
        ["Benefício", "Como a automação entrega"],
        ["Resposta mais rápida", "Todo relato novo recebe protocolo e prioridade na execução seguinte do robô (agendado de hora em hora), em vez de esperar triagem manual."],
        ["Urgência para quem mais precisa", "Relato de pessoa com deficiência ou idosa junto a um ponto de ônibus sai com prioridade alta, por regra, sem depender de julgamento caso a caso."],
        ["Transparência", "O cidadão vê no mapa o status (encaminhado, resolvido) e o protocolo. Quando a prefeitura conclui, o relato é fechado automaticamente e deixa de contar como obstáculo em aberto."],
        ["Menos ruído para a prefeitura", "Relatos repetidos do mesmo obstáculo viram um único chamado; relatos sem localização válida não são enviados."],
    ], [0.3, 0.7]))

    # ---- 4
    h.append(p("4. Descrição do processo e desenho do fluxo", E_H1))
    h.append(p("O robô é um programa Python executado por agendador (Agendador de Tarefas do Windows, cron ou modo contínuo <font face='Courier'>--loop</font>). "
               "Cada execução percorre as etapas abaixo. O desenho completo em BPMN 2.0 está no repositório em "
               "<font face='Courier'>docs/processo.bpmn</font> (abre no Camunda Modeler ou em demo.bpmn.io)."))
    h.append(tabela([
        ["Elemento", "Descrição"],
        ["Início", "Agendado, a cada hora. Uma trava impede duas execuções ao mesmo tempo."],
        ["Entradas", "(a) API do MVP: relatos com status novo, relatos em aberto e pontos de ônibus; (b) arquivo CSV de retorno da prefeitura na pasta de entrada; (c) serviço público de endereços do OpenStreetMap (Nominatim)."],
        ["Etapas", "1. Verificar a API. 2. Ler o retorno da prefeitura e fechar relatos concluídos. 3. Buscar relatos novos. 4. Para cada relato: validar, procurar duplicado, definir prioridade, buscar endereço, gerar protocolo, atualizar o MVP e gravar o chamado. 5. Gravar logs, auditoria e resumo."],
        ["Decisões", "API responde? Arquivo de retorno válido? Relato válido? Relato duplicado? Qual prioridade (R1, R2, R3)? Situação do chamado (concluído, em andamento, indeferido)?"],
        ["Repetições", "Laço sobre a coleção de relatos novos; laço sobre os arquivos de retorno e sobre as linhas de cada arquivo."],
        ["Exceções", "API fora do ar, credencial recusada, erro em um relato, arquivo ausente, arquivo inválido, linha inválida, protocolo desconhecido, serviço de endereços fora do ar, falha ao gravar o chamado, execução simultânea."],
        ["Saídas", "Relatos atualizados no MVP (status, prioridade, protocolo, referência ao original); lote de chamados em CSV; arquivos de retorno movidos para processados ou rejeitados; log, trilha de auditoria e resumo da execução."],
    ], [0.18, 0.82]))
    h.append(Spacer(1, 6))
    h.append(imagem(RPA / "docs" / "processo.png", LARGURA_UTIL))
    h.append(p("Figura 1. Fluxo do processo automatizado (gerado de docs/gerar_diagrama.py, mesma definição do arquivo .bpmn).", E_LEG))
    h.append(p("<b>Limite da demonstração.</b> O canal SP156 da Prefeitura de São Paulo não oferece interface pública para abertura de chamados "
               "por sistemas. Por isso o robô entrega o <i>lote de chamados</i> em arquivo estruturado, no formato que seria enviado ao canal, e "
               "consome um <i>arquivo de retorno</i> com a situação dos protocolos. Os arquivos de retorno e os relatos usados na demonstração são "
               "fictícios, criados pelo roteiro <font face='Courier'>tests/preparar_cenario.py</font>. As consultas de endereço são reais."))

    # ---- 5
    h.append(p("5. Tecnologias utilizadas e justificativa", E_H1))
    h.append(tabela([
        ["Tecnologia", "Uso", "Por que foi escolhida"],
        ["Python 3.11+", "Linguagem do robô", "Aceita pela disciplina, versionável no GitHub, roda em qualquer servidor sem licença e é a mesma linguagem da API do MVP."],
        ["httpx", "Chamadas HTTP à API do MVP e ao serviço de endereços", "Cliente moderno com controle de tempo limite; permite simular a API nos testes sem rede."],
        ["Biblioteca padrão (csv, logging, json, argparse, dataclasses)", "Leitura do retorno, logs, auditoria, linha de comando", "Menos dependências externas: instalação simples e menor superfície de ataque."],
        ["pytest", "Testes automatizados de sucesso, decisão e falha", "Padrão de mercado; a suíte roda em segundos e serve de evidência reproduzível."],
        ["API REST do MVP (FastAPI)", "Integração: leitura e atualização dos relatos", "Contrato claro entre componentes, como pede o desafio (API em vez de prints lado a lado)."],
        ["Nominatim / OpenStreetMap", "Endereço aproximado a partir da coordenada", "Dado aberto e gratuito, sem chave. Usado dentro da política do serviço (1 consulta por segundo, com cache)."],
        ["BPMN 2.0", "Desenho do processo", "Notação pedida pela disciplina; o arquivo abre em ferramentas livres."],
    ], [0.24, 0.3, 0.46]))

    # ---- 6
    h.append(p("6. Regras de negócio, decisões e processamento", E_H1))
    h.append(p("As regras ficam isoladas em <font face='Courier'>src/passo_livre_rpa/regras.py</font>, como funções sem efeitos colaterais, o que facilita teste e auditoria."))
    h.append(p("Validação do relato", E_H2))
    h.append(tabela([
        ["Regra", "Condição para rejeitar", "Ação"],
        ["V1", "Tipo de obstáculo fora do domínio do produto", "Status inválido; não gera chamado"],
        ["V2", "Coordenada ausente ou fora da área atendida (município de São Paulo)", "Status inválido; não gera chamado"],
        ["V3", "Data ausente, ilegível ou no futuro", "Status inválido; não gera chamado"],
    ], [0.1, 0.55, 0.35]))
    h.append(p("Duplicidade", E_H2))
    h.append(p("Um relato é duplicado quando existe outro <b>em aberto</b> (validado ou encaminhado), do <b>mesmo tipo</b>, a até <b>20 metros</b> e criado nos "
               "últimos <b>30 dias</b>. Os relatos são processados do mais antigo para o mais novo e cada relato encaminhado entra na comparação "
               "dos seguintes, de modo que duplicados dentro do mesmo lote também são identificados. O relato duplicado recebe o status "
               "duplicado e a referência ao original; nenhum chamado novo é gerado."))
    h.append(p("Prioridade", E_H2))
    h.append(tabela([
        ["Regra", "Condição", "Prioridade"],
        ["R1", "Perfil prioritário (pessoa com deficiência ou idosa) E obstáculo a até 60 m de um ponto de ônibus", "Alta"],
        ["R2", "Perfil prioritário OU obstáculo a até 60 m de um ponto de ônibus", "Média"],
        ["R3", "Demais casos", "Normal"],
    ], [0.1, 0.72, 0.18]))
    h.append(p("Retorno da prefeitura", E_H2))
    h.append(tabela([
        ["Situação no arquivo", "Ação do robô"],
        ["CONCLUIDO", "Localiza o relato pelo protocolo e marca como resolvido (o MVP registra a data e recalcula o tempo médio de resolução)."],
        ["EM_ANDAMENTO", "Nenhuma alteração; apenas registra na auditoria."],
        ["INDEFERIDO", "Não altera o relato e registra alerta para revisão humana: a decisão de encerrar um relato negado fica com uma pessoa."],
    ], [0.25, 0.75]))
    h.append(p("Raios, janela de tempo e área atendida são parâmetros de ambiente (arquivo <font face='Courier'>.env</font>), não constantes escondidas no código. "
               "O protocolo é determinístico (<font face='Courier'>PL-AAAAMMDD-número do relato</font>), o que evita protocolos diferentes para o mesmo relato."))

    # ---- 7
    h.append(p("7. Tratamento de exceções e recuperação", E_H1))
    h.append(p("Princípio adotado: <b>nenhuma falha é silenciosa</b>. Toda exceção vira linha de log, evento de auditoria e contador no resumo, e o "
               "processo termina com código de saída que o agendador consegue monitorar (0 sucesso, 1 sucesso com falhas, 2 abortado, 3 já em execução)."))
    h.append(tabela([
        ["Situação", "O que o robô faz", "Recuperação"],
        ["API do MVP fora do ar ou erro 5xx", "Repete até 3 vezes com espera progressiva (2 s, 4 s). Persistindo, registra o erro e encerra com código 2.", "Nada é alterado; a próxima execução retoma do zero."],
        ["API cai no meio do lote", "Após duas falhas seguidas de conexão, encerra o lote e registra quantos relatos ficaram pendentes.", "Relatos já encaminhados permanecem válidos e rastreáveis; os pendentes continuam como novos."],
        ["Credencial da automação recusada (401/403)", "Aborta na primeira recusa com mensagem clara, sem insistir relato por relato.", "Corrigir o token e executar de novo."],
        ["API recusa a atualização de um relato (4xx)", "Registra a falha daquele relato e segue para o próximo.", "O relato continua como novo e volta na execução seguinte."],
        ["Arquivo de retorno ausente", "Registra que a etapa foi ignorada e segue para a triagem.", "Não é erro: o arquivo é opcional."],
        ["Arquivo de retorno inválido (vazio, cabeçalho errado, codificação errada)", "Move para a pasta rejeitados, registra o motivo e segue.", "Arquivo fica preservado para análise; execução termina como sucesso com falhas."],
        ["Linha inválida no retorno (situação desconhecida, data errada, protocolo repetido)", "Ignora só a linha, registra o número da linha e o motivo, processa as demais.", "Arquivo vai para processados com as ocorrências na auditoria."],
        ["Protocolo do retorno não existe no MVP", "Registra alerta e não altera nada.", "Fica na auditoria para conferência."],
        ["Relato duplicado ou inconsistente", "Marca como duplicado (com referência ao original) ou inválido.", "Não gera chamado."],
        ["Serviço de endereços fora do ar", "Segue sem endereço. Após 3 falhas seguidas desliga a consulta até o fim da execução, para não atrasar o lote.", "O chamado sai com coordenadas; endereço é complementar."],
        ["Falha ao gravar o lote de chamados", "Desfaz a atualização do relato no MVP e registra a falha.", "O relato volta a ser novo e é reprocessado."],
        ["Duas execuções ao mesmo tempo", "A segunda encontra a trava e encerra com código 3 sem processar. Trava com mais de 2 horas é considerada abandonada.", "Evita chamados em dobro."],
        ["Reexecução", "Como só relatos com status novo são lidos e arquivos lidos saem da entrada, repetir a execução não duplica nada.", "Idempotência verificada em teste."],
    ], [0.27, 0.43, 0.3]))

    # ---- 8
    h.append(p("8. Logs e evidências de auditoria", E_H1))
    h.append(p("Cada execução produz três artefatos na pasta <font face='Courier'>logs/</font>: o <b>log legível</b> (uma linha por acontecimento, com data e "
               "hora, nível e identificador da execução), a <b>trilha de auditoria</b> em JSON Lines (um evento por item processado) e o <b>resumo</b> da "
               "execução com os totais. Nenhum deles contém descrição livre, perfil ou identificador do cidadão: os registros citam apenas o número "
               "do relato, o tipo de obstáculo e o código da regra aplicada. Os trechos abaixo são das execuções reais da demonstração."))
    if principal:
        h.append(p(f"Log da execução completa ({escape(principal['execucao'])})", E_H2))
        h.append(mono(linhas_do_log(principal["execucao"])))
        h.append(p("Trilha de auditoria da mesma execução (primeiros eventos)", E_H2))
        h.append(mono(eventos_de_auditoria(principal["execucao"])[:9]))
        h.append(p("Resumo da execução", E_H2))
        h.append(mono(json.dumps(principal, ensure_ascii=False, indent=1).splitlines()))
    else:
        h.append(p(falta("execute a demonstração para gerar os logs")))

    # ---- 9
    h.append(p("9. Integração com o MVP", E_H1))
    h.append(p("A integração é feita pela <b>API REST do MVP</b>. O robô lê e atualiza os relatos; o resultado é consumido pelo aplicativo web: a tela "
               "Chamados lista cada relato com situação, prioridade e protocolo, o mapa apaga os obstáculos resolvidos e o painel recalcula os "
               "indicadores. As telas se atualizam sozinhas a cada 5 segundos, sem recarregar a página. "
               "A alteração de relatos exige o cabeçalho <font face='Courier'>X-Automation-Token</font>, cujo valor fica em variável de ambiente."))
    h.append(tabela([
        ["Chamada", "Uso pelo robô"],
        ["GET /health", "Verificação inicial de disponibilidade"],
        ["GET /relatos?status=novo", "Coleção a processar"],
        ["GET /relatos?status=validado | encaminhado", "Relatos em aberto para a busca de duplicados"],
        ["GET /relatos?protocolo=...", "Localiza o relato citado no retorno da prefeitura"],
        ["GET /pontos", "Pontos de ônibus para a regra de prioridade"],
        ["PATCH /relatos/{id}", "Grava status, prioridade, protocolo e referência ao original"],
    ], [0.42, 0.58]))
    antes = {r["id"]: r for r in carregar_json(RPA / "tests" / "evidencias" / "01_estado_mvp_antes.json", [])}
    depois = {r["id"]: r for r in carregar_json(RPA / "tests" / "evidencias" / "02_estado_mvp_depois.json", [])}
    mudou = [(a, depois[i]) for i, a in antes.items() if i in depois and depois[i] != a]
    if mudou:
        h.append(p("Estado dos relatos no MVP antes e depois da execução completa", E_H2))
        linhas = [["Relato", "Tipo", "Antes", "Depois", "Prioridade", "Protocolo / original"]]
        for a, d in mudou:
            ref = d.get("protocolo") or (f"duplicado do relato {d['duplicado_de']}" if d.get("duplicado_de") else "")
            linhas.append([str(a["id"]), escape(a["tipo"]), escape(a["status"]), f"<b>{escape(d['status'])}</b>", escape(d.get("prioridade") or ""), escape(ref)])
        h.append(tabela(linhas, [0.08, 0.2, 0.14, 0.14, 0.13, 0.31]))
        h.append(p("Fonte: consultas GET /relatos gravadas em tests/evidencias/ antes e depois da execução.", E_LEG))
    arquivo_chamados = RPA / "tests" / "evidencias" / (principal.get("arquivo_chamados") or "-")
    if arquivo_chamados.is_file():
        h.append(p("Lote de chamados gerado (arquivo estruturado de saída)", E_H2))
        with arquivo_chamados.open(encoding="utf-8-sig", newline="") as f:
            chamados = list(csv.DictReader(f, delimiter=";"))
        linhas = [["Protocolo", "Tipo", "Prior.", "Regra", "Endereço (OpenStreetMap)", "Ponto de ônibus"]]
        linhas += [[c["protocolo"], escape(c["tipo"]), c["prioridade"], c["regra_prioridade"], escape(c["endereco"]),
                    escape(f"{c['ponto_onibus_nome']} ({c['distancia_ponto_m']} m)" if c["ponto_onibus_nome"] else "")] for c in chamados]
        h.append(tabela(linhas, [0.21, 0.19, 0.08, 0.08, 0.26, 0.18]))
    capturas = [
        ("app_chamados_antes.png", "Tela Chamados do aplicativo antes da execução: relatos novos aguardando a automação."),
        ("app_chamados_depois.png", "A mesma tela depois da execução: situação, prioridade e protocolo gravados pelo robô."),
        ("app_mapa_depois.png", "Mapa do aplicativo depois da execução, com a lista de relatos e seus protocolos."),
    ]
    numero = 2
    for arquivo, legenda in capturas:
        if (RPA / "assets" / arquivo).is_file():
            h.append(KeepTogether([imagem(RPA / "assets" / arquivo, 0.76 * LARGURA_UTIL), p(f"Figura {numero}. {legenda}", E_LEG)]))
            numero += 1

    # ---- 10
    h.append(p("10. Testes realizados", E_H1))
    h.append(p(f"<b>Testes automatizados.</b> A suíte em <font face='Courier'>tests/</font> executa o robô inteiro contra uma API do MVP simulada em memória, "
               f"o que permite provocar cada falha de forma controlada, e testa a API real do aplicativo nos pontos de que o robô depende. Resultado da execução feita na geração deste relatório: <b>{escape(resultado_testes)}</b>."))
    linhas = [["Cenário", "Qtde", "Casos de teste"]]
    for nome, testes in categorias.items():
        linhas.append([nome, str(len(testes)), escape(", ".join(t.removeprefix("test_") for t in testes))])
    h.append(tabela(linhas, [0.2, 0.08, 0.72]))
    h.append(p("<b>Execuções de ponta a ponta.</b> O robô também foi executado contra o MVP real, em ambiente local, com o cenário criado por "
               "<font face='Courier'>tests/preparar_cenario.py</font>. Cada linha abaixo vem do arquivo de resumo gravado pelo próprio robô."))
    linhas = [["Execução", "O que demonstra", "Situação", "Lidos", "Encam.", "Dupl.", "Inv.", "Falhas", "Saída"]]
    codigos = {"sucesso": 0, "sucesso_com_falhas": 1, "abortado": 2, "ja_em_execucao": 3}
    for r in resumos:
        linhas.append([r.get("execucao", ""), descrever(r), r.get("situacao", ""), str(r.get("relatos_lidos", 0)), str(r.get("encaminhados", 0)),
                       str(r.get("duplicados", 0)), str(r.get("invalidos", 0)), str(r.get("falhas", 0)), str(codigos.get(r.get("situacao", ""), "?"))])
    h.append(tabela(linhas, [0.17, 0.33, 0.16, 0.06, 0.07, 0.06, 0.05, 0.06, 0.06]) if resumos else p(falta("execute a demonstração")))
    for titulo, r in (("Log do cenário de falha: API fora do ar", fora_do_ar), ("Log do cenário de falha: credencial recusada", recusada)):
        if r:
            h.append(p(titulo, E_H2))
            h.append(mono(linhas_do_log(r["execucao"])))

    # ---- 11
    h.append(p("11. Considerações de segurança e LGPD", E_H1))
    h.append(tabela([
        ["Tema", "Medida adotada"],
        ["Credenciais", "O token da automação e a URL da API ficam em variáveis de ambiente (arquivo .env fora do repositório; o repositório traz só o .env.example). Nenhum segredo no código."],
        ["Controle de acesso", "A alteração de relatos no MVP exige o token da automação, comparado em tempo constante. Sem o token correto o robô não altera nada."],
        ["Minimização de dados", "O robô só lê o que precisa para decidir. O MVP nunca armazena nome ou e-mail do cidadão: guarda um código embaralhado (hash com sal)."],
        ["Dado sensível", "O perfil do cidadão (pessoa com deficiência, idosa) é dado sensível. Ele é usado apenas para calcular a prioridade e não é copiado para o lote de chamados, para os logs nem para a auditoria; neles aparece só o código da regra."],
        ["Logs", "Sem descrição livre, sem hash do cidadão, sem perfil. Um teste automatizado falha se qualquer um desses dados aparecer em log, auditoria ou arquivo de saída."],
        ["Compartilhamento com terceiros", "Ao serviço de endereços é enviada somente a coordenada do obstáculo, que não identifica pessoa. À prefeitura segue o lote com tipo, local, prioridade e protocolo."],
        ["Pessoa no circuito", "Chamado indeferido pela prefeitura não encerra o relato automaticamente: gera alerta para revisão humana."],
        ["Integridade", "Trava contra execução simultânea, protocolo determinístico e processamento idempotente evitam chamados em dobro."],
        ["Rastreabilidade", "Cada decisão fica registrada com data, hora, execução, relato e regra aplicada, o que permite explicar ao cidadão por que seu relato recebeu determinada prioridade."],
    ], [0.24, 0.76]))

    # ---- 12
    h.append(p("12. Links", E_H1))
    h.append(tabela([
        ["Item", "Endereço"],
        ["Repositório GitHub", ou_falta(repositorio, "link do repositório em docs/equipe.json")],
        ["Vídeo demonstrativo (até 3 minutos)", ou_falta(video, "link do vídeo em docs/equipe.json")],
        ["MVP", escape(equipe.get("url_mvp") or "") or "Executado em ambiente local, a partir deste repositório (passos abaixo)."],
    ], [0.38, 0.62]))
    h.append(p("Como reproduzir", E_H2))
    h.append(mono([
        "# 1. instalar (na raiz do repositório)    pip install -r requirements.txt && pip install -e .",
        "# 2. subir o aplicativo (MVP)             python -m uvicorn app.main:app --app-dir mvp --port 8000",
        "# 3. criar o cenário de demonstração      python tests/preparar_cenario.py --retorno-invalido",
        "# 4. executar o robô                      python -m passo_livre_rpa",
        "# 5. rodar os testes                      python -m pytest -q",
        "# 6. regerar diagrama e este relatório    python docs/gerar_diagrama.py && python docs/gerar_relatorio.py",
    ]))
    return h


INICIO, FIM = "<!-- equipe:inicio -->", "<!-- equipe:fim -->"


def atualizar_readme() -> None:
    """Reescreve no README o bloco de integrantes e links, a partir de docs/equipe.json."""
    readme = RPA / "README.md"
    if not readme.is_file():
        return
    texto = readme.read_text(encoding="utf-8")
    if INICIO not in texto or FIM not in texto:
        return
    equipe = carregar_json(RPA / "docs" / "equipe.json", {})
    integrantes = [i for i in equipe.get("integrantes", []) if i.get("nome") or i.get("rm")]
    pendente = "_preencher em docs/equipe.json_"
    linhas = ["| Nome completo | RM |", "|---|---|"]
    linhas += [f"| {i.get('nome') or pendente} | {i.get('rm') or pendente} |" for i in integrantes] or [f"| {pendente} | {pendente} |"]
    linhas += ["", f"- **Vídeo demonstrativo (até 3 minutos):** {equipe.get('video') or pendente}",
               f"- **Repositório:** {equipe.get('repositorio') or pendente}"]
    if equipe.get("url_mvp"):
        linhas.append(f"- **MVP publicado:** {equipe['url_mvp']}")
    bloco = INICIO + "\n" + "\n".join(linhas) + "\n" + FIM
    novo = texto[: texto.index(INICIO)] + bloco + texto[texto.index(FIM) + len(FIM):]
    if novo != texto:
        readme.write_text(novo, encoding="utf-8", newline="\n")
        print(f"atualizado: {readme}")


def main() -> None:
    doc = SimpleDocTemplate(str(SAIDA), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title="Relatório Técnico de RPA - Passo Livre", author="Equipe Passo Livre")
    doc.build(montar(), onFirstPage=rodape, onLaterPages=rodape)
    print(f"gerado: {SAIDA}")
    atualizar_readme()


if __name__ == "__main__":
    main()
