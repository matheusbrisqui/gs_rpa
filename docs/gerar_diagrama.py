"""Gera o desenho do processo em dois formatos a partir de uma única definição:

- `processo.bpmn`  BPMN 2.0 com diagrama (abre no Camunda Modeler ou em https://demo.bpmn.io);
- `processo.png`   imagem para o relatório e o README.

Uso:  python docs/gerar_diagrama.py
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from PIL import Image, ImageDraw, ImageFont

AQUI = Path(__file__).resolve().parent
LARGURA, ALTURA = 1250, 640
TW, TH = 140, 70      # tarefa
G = 50                # gateway (losango)
E = 36                # evento (círculo)

# id: (tipo, x_centro, y_centro, rótulo)
NOS = {
    "inicio":     ("inicio", 60, 200, "Início agendado (a cada hora)"),
    "t_saude":    ("servico", 180, 200, "Verificar se a API do MVP está no ar"),
    "g_api":      ("gateway", 310, 200, "API responde?"),
    "t_aborta":   ("servico", 470, 70, "Registrar falha após 3 tentativas"),
    "fim_erro":   ("fim_erro", 600, 70, "Fim com erro (código 2)"),
    "t_retorno":  ("servico", 440, 200, "Ler arquivo de retorno da prefeitura"),
    "g_arquivo":  ("gateway", 570, 200, "Arquivo válido?"),
    "t_rejeita":  ("servico", 760, 70, "Mover para rejeitados e registrar"),
    "t_resolve":  ("servico", 700, 200, "Marcar relatos concluídos como resolvidos"),
    "t_busca":    ("servico", 880, 200, "Buscar relatos novos e pontos de ônibus"),
    "g_loop":     ("gateway", 130, 370, "Há relato a processar?"),
    "t_valida":   ("regra", 270, 370, "Validar dados do relato"),
    "g_valido":   ("gateway", 400, 370, "Válido?"),
    "t_dup":      ("regra", 530, 370, "Procurar relato igual em aberto (até 20 m)"),
    "g_dup":      ("gateway", 660, 370, "Duplicado?"),
    "t_prio":     ("regra", 790, 370, "Definir prioridade (R1, R2 ou R3)"),
    "t_endereco": ("servico", 950, 370, "Buscar endereço (se falhar, segue sem)"),
    "t_encaminha": ("servico", 1110, 370, "Gerar protocolo, atualizar MVP e gravar chamado"),
    "t_invalido": ("servico", 400, 490, "Marcar relato como inválido"),
    "t_marca_dup": ("servico", 660, 490, "Marcar como duplicado do original"),
    "t_resumo":   ("servico", 130, 490, "Gravar logs, auditoria e resumo"),
    "fim":        ("fim", 260, 490, "Fim"),
}

RETORNO = [(1215, 370), (1215, 585), (30, 585), (30, 370), (105, 370)]  # volta ao início do laço

# id: (origem, destino, rótulo, pontos do caminho)
FLUXOS = {
    "f01": ("inicio", "t_saude", "", [(78, 200), (110, 200)]),
    "f02": ("t_saude", "g_api", "", [(250, 200), (285, 200)]),
    "f03": ("g_api", "t_aborta", "Não", [(310, 175), (310, 70), (400, 70)]),
    "f04": ("t_aborta", "fim_erro", "", [(540, 70), (582, 70)]),
    "f05": ("g_api", "t_retorno", "Sim", [(335, 200), (370, 200)]),
    "f06": ("t_retorno", "g_arquivo", "", [(510, 200), (545, 200)]),
    "f07": ("g_arquivo", "t_rejeita", "Não", [(570, 175), (570, 125), (760, 125), (760, 105)]),
    "f08": ("g_arquivo", "t_resolve", "Sim", [(595, 200), (630, 200)]),
    "f09": ("t_rejeita", "t_busca", "", [(830, 70), (880, 70), (880, 165)]),
    "f10": ("t_resolve", "t_busca", "", [(770, 200), (810, 200)]),
    "f11": ("t_busca", "g_loop", "", [(880, 235), (880, 290), (130, 290), (130, 345)]),
    "f12": ("g_loop", "t_valida", "Sim", [(155, 370), (200, 370)]),
    "f13": ("g_loop", "t_resumo", "Não", [(130, 395), (130, 455)]),
    "f14": ("t_resumo", "fim", "", [(200, 490), (242, 490)]),
    "f15": ("t_valida", "g_valido", "", [(340, 370), (375, 370)]),
    "f16": ("g_valido", "t_dup", "Sim", [(425, 370), (460, 370)]),
    "f17": ("g_valido", "t_invalido", "Não", [(400, 395), (400, 455)]),
    "f18": ("t_dup", "g_dup", "", [(600, 370), (635, 370)]),
    "f19": ("g_dup", "t_prio", "Não", [(685, 370), (720, 370)]),
    "f20": ("g_dup", "t_marca_dup", "Sim", [(660, 395), (660, 455)]),
    "f21": ("t_prio", "t_endereco", "", [(860, 370), (880, 370)]),
    "f22": ("t_endereco", "t_encaminha", "", [(1020, 370), (1040, 370)]),
    "f23": ("t_encaminha", "g_loop", "", [(1180, 370), *RETORNO]),
    "f24": ("t_invalido", "g_loop", "", [(400, 525), (400, 585), *RETORNO[2:]]),
    "f25": ("t_marca_dup", "g_loop", "", [(660, 525), (660, 585), *RETORNO[2:]]),
}

NOTA = {
    "id": "nota_falhas",
    "alvo": "t_encaminha",
    "caixa": (790, 455, 400, 78),  # x, y, largura, altura
    "texto": (
        "Falha em um relato: registra o erro, mantém o relato como novo e passa ao próximo. "
        "Duas quedas seguidas da API ou token recusado encerram o lote com erro."
    ),
}

# Onde fica o rótulo de cada losango, para não cobrir tarefas nem setas
POSICAO_ROTULO = {"g_api": "abaixo", "g_arquivo": "abaixo", "g_loop": "acima_esquerda", "g_valido": "acima", "g_dup": "acima"}


def caixa_rotulo(nid: str, x: int, y: int) -> tuple[int, int, int, int]:
    """Área (x, y, largura, altura) do rótulo de um losango."""
    pos = POSICAO_ROTULO[nid]
    if pos == "abaixo":
        return x - 60, y + G // 2 + 6, 120, 30
    if pos == "acima":
        return x - 60, y - G // 2 - 24, 120, 18
    return x - 98, y - G // 2 - 34, 90, 30  # acima, à esquerda da seta que chega por cima


def fonte(tamanho: int):
    """Fonte com acentos: Arial (Windows), DejaVu ou Liberation (Linux); por último a padrão do Pillow."""
    for nome in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(size=tamanho)


TAG = {"servico": "serviceTask", "regra": "businessRuleTask", "gateway": "exclusiveGateway",
       "inicio": "startEvent", "fim": "endEvent", "fim_erro": "endEvent"}


def caixa(tipo: str, x: int, y: int) -> tuple[int, int, int, int]:
    """Devolve (x, y, largura, altura) do elemento a partir do centro."""
    if tipo in ("servico", "regra"):
        return x - TW // 2, y - TH // 2, TW, TH
    if tipo == "gateway":
        return x - G // 2, y - G // 2, G, G
    return x - E // 2, y - E // 2, E, E


# ------------------------------------------------------------------ BPMN 2.0
def gerar_bpmn() -> str:
    proc, di = [], []
    for nid, (tipo, x, y, rotulo) in NOS.items():
        entradas = "".join(f"<bpmn:incoming>{f}</bpmn:incoming>" for f, v in FLUXOS.items() if v[1] == nid)
        saidas = "".join(f"<bpmn:outgoing>{f}</bpmn:outgoing>" for f, v in FLUXOS.items() if v[0] == nid)
        extra = {"inicio": "<bpmn:timerEventDefinition/>", "fim_erro": "<bpmn:errorEventDefinition/>"}.get(tipo, "")
        proc.append(f"<bpmn:{TAG[tipo]} id={quoteattr(nid)} name={quoteattr(rotulo)}>{entradas}{saidas}{extra}</bpmn:{TAG[tipo]}>")
        bx, by, bw, bh = caixa(tipo, x, y)
        marcador = ' isMarkerVisible="true"' if tipo == "gateway" else ""
        rot = ""
        if tipo not in ("servico", "regra"):
            lx, ly, lw, lh = caixa_rotulo(nid, x, y) if tipo == "gateway" else (bx - 30, by + bh + 4, 96, 28)
            rot = f'<bpmndi:BPMNLabel><dc:Bounds x="{lx}" y="{ly}" width="{lw}" height="{lh}"/></bpmndi:BPMNLabel>'
        di.append(
            f'<bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"{marcador}>'
            f'<dc:Bounds x="{bx}" y="{by}" width="{bw}" height="{bh}"/>{rot}</bpmndi:BPMNShape>'
        )
    for fid, (origem, destino, rotulo, pontos) in FLUXOS.items():
        nome = f" name={quoteattr(rotulo)}" if rotulo else ""
        proc.append(f'<bpmn:sequenceFlow id="{fid}" sourceRef="{origem}" targetRef="{destino}"{nome}/>')
        caminho = "".join(f'<di:waypoint x="{x}" y="{y}"/>' for x, y in pontos)
        di.append(f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{caminho}</bpmndi:BPMNEdge>')

    nx, ny, nw, nh = NOTA["caixa"]
    _, ax, ay, _ = NOS[NOTA["alvo"]]
    proc.append(f'<bpmn:textAnnotation id="{NOTA["id"]}"><bpmn:text>{escape(NOTA["texto"])}</bpmn:text></bpmn:textAnnotation>')
    proc.append(f'<bpmn:association id="assoc_nota" sourceRef="{NOTA["alvo"]}" targetRef="{NOTA["id"]}"/>')
    di.append(f'<bpmndi:BPMNShape id="{NOTA["id"]}_di" bpmnElement="{NOTA["id"]}"><dc:Bounds x="{nx}" y="{ny}" width="{nw}" height="{nh}"/></bpmndi:BPMNShape>')
    di.append(
        f'<bpmndi:BPMNEdge id="assoc_nota_di" bpmnElement="assoc_nota">'
        f'<di:waypoint x="{ax}" y="{ay + TH // 2}"/><di:waypoint x="{ax}" y="{ny}"/></bpmndi:BPMNEdge>'
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
        'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
        'id="Definitions_PassoLivreRPA" targetNamespace="https://github.com/passo-livre/rpa">\n'
        '<bpmn:process id="Process_RelatoAoChamado" name="Passo Livre - do relato ao chamado" isExecutable="false">\n'
        + "\n".join(proc)
        + '\n</bpmn:process>\n<bpmndi:BPMNDiagram id="Diagrama_1">'
        '<bpmndi:BPMNPlane id="Plano_1" bpmnElement="Process_RelatoAoChamado">\n'
        + "\n".join(di)
        + "\n</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>\n</bpmn:definitions>\n"
    )


# ------------------------------------------------------------------ PNG
S = 2  # fator de escala para a imagem ficar nítida no PDF
COR = {"linha": "#1f2937", "tarefa": "#e8f1fd", "regra": "#fdf3d7", "gateway": "#ffffff",
       "inicio": "#1b7f3b", "fim": "#b3261e", "texto": "#111827", "nota": "#4b5563"}


def _quebrar(desenho, texto: str, fonte, largura: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if desenho.textlength(tentativa, font=fonte) <= largura or not atual:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    return [*linhas, atual] if atual else linhas


def _texto_central(desenho, cx, cy, texto, fonte, largura, cor):
    linhas = _quebrar(desenho, texto, fonte, largura)
    alt = fonte.size + 3 * S
    y = cy - alt * len(linhas) / 2
    for linha in linhas:
        w = desenho.textlength(linha, font=fonte)
        desenho.text((cx - w / 2, y), linha, font=fonte, fill=cor)
        y += alt


def _seta(desenho, pontos, cor, tracejada=False):
    pts = [(x * S, y * S) for x, y in pontos]
    if tracejada:
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        passos = max(1, int(abs(y1 - y0 + x1 - x0) // (6 * S)))
        for i in range(0, passos, 2):
            a, b = i / passos, min(1, (i + 1) / passos)
            desenho.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)], fill=cor, width=S)
        return
    desenho.line(pts, fill=cor, width=int(1.5 * S), joint="curve")
    (xa, ya), (xb, yb) = pts[-2], pts[-1]
    t = 7 * S
    if xa == xb:  # vertical
        s = 1 if yb > ya else -1
        ponta = [(xb, yb), (xb - t / 2, yb - s * t), (xb + t / 2, yb - s * t)]
    else:
        s = 1 if xb > xa else -1
        ponta = [(xb, yb), (xb - s * t, yb - t / 2), (xb - s * t, yb + t / 2)]
    desenho.polygon(ponta, fill=cor)


def gerar_png(destino: Path) -> None:
    img = Image.new("RGB", (LARGURA * S, ALTURA * S), "white")
    d = ImageDraw.Draw(img)
    f_tarefa = fonte(11 * S)
    f_rotulo = fonte(10 * S)
    f_titulo = fonte(15 * S)
    d.text((20 * S, 12 * S), "Passo Livre | Processo automatizado: do relato ao chamado", font=f_titulo, fill=COR["texto"])

    for _fid, (_o, _d, rotulo, pontos) in FLUXOS.items():
        _seta(d, pontos, COR["linha"])
        if rotulo:
            (x0, y0), (_, y1) = pontos[0], pontos[1]
            if y0 == y1:
                pos = (x0 + 5, y0 - 16)
            elif y1 > y0:
                pos = (x0 + 6, y0 + 6)
            else:
                pos = (x0 + 6, y0 - 22)
            d.text((pos[0] * S, pos[1] * S), rotulo, font=f_rotulo, fill=COR["texto"])

    nx, ny, nw, nh = NOTA["caixa"]
    _, ax, ay, _ = NOS[NOTA["alvo"]]
    _seta(d, [(ax, ay + TH // 2), (ax, ny)], COR["nota"], tracejada=True)
    d.line([((nx + 10) * S, ny * S), (nx * S, ny * S), (nx * S, (ny + nh) * S), ((nx + 10) * S, (ny + nh) * S)], fill=COR["nota"], width=S)
    y = ny + 8
    for linha in _quebrar(d, NOTA["texto"], f_rotulo, (nw - 20) * S):
        d.text(((nx + 10) * S, y * S), linha, font=f_rotulo, fill=COR["nota"])
        y += 15

    for nid, (tipo, x, y, rotulo) in NOS.items():
        bx, by, bw, bh = caixa(tipo, x, y)
        ret = [bx * S, by * S, (bx + bw) * S, (by + bh) * S]
        if tipo in ("servico", "regra"):
            d.rounded_rectangle(ret, radius=9 * S, fill=COR["tarefa" if tipo == "servico" else "regra"], outline=COR["linha"], width=int(1.5 * S))
            _texto_central(d, x * S, y * S, rotulo, f_tarefa, (TW - 14) * S, COR["texto"])
        elif tipo == "gateway":
            m = G // 2
            d.polygon([(x * S, (y - m) * S), ((x + m) * S, y * S), (x * S, (y + m) * S), ((x - m) * S, y * S)], fill=COR["gateway"], outline=COR["linha"], width=int(1.5 * S))
            c = 8
            d.line([((x - c) * S, (y - c) * S), ((x + c) * S, (y + c) * S)], fill=COR["linha"], width=2 * S)
            d.line([((x - c) * S, (y + c) * S), ((x + c) * S, (y - c) * S)], fill=COR["linha"], width=2 * S)
            lx, ly, lw, _ = caixa_rotulo(nid, x, y)
            direita =POSICAO_ROTULO[nid] == "acima_esquerda"
            yy = ly
            for linha in _quebrar(d, rotulo, f_rotulo, lw * S):
                w = d.textlength(linha, font=f_rotulo)
                xx = (lx + lw) * S - w if direita else (lx + lw / 2) * S - w / 2
                d.text((xx, yy * S), linha, font=f_rotulo, fill=COR["texto"])
                yy += 14
        else:
            cor = COR["inicio"] if tipo == "inicio" else COR["fim"]
            d.ellipse(ret, fill="white", outline=cor, width=(2 if tipo == "inicio" else 4) * S)
            linhas = _quebrar(d, rotulo, f_rotulo, 84 * S)
            yy = by + bh + 5
            for linha in linhas:
                w = d.textlength(linha, font=f_rotulo)
                d.text((x * S - w / 2, yy * S), linha, font=f_rotulo, fill=COR["texto"])
                yy += 14

    lx, ly = 20, ALTURA - 28
    for cor, texto in ((COR["tarefa"], "Tarefa automática (API, arquivo, log)"), (COR["regra"], "Regra de negócio")):
        d.rounded_rectangle([lx * S, ly * S, (lx + 22) * S, (ly + 14) * S], radius=3 * S, fill=cor, outline=COR["linha"], width=S)
        d.text(((lx + 28) * S, (ly - 1) * S), texto, font=f_rotulo, fill=COR["texto"])
        lx += 40 + int(d.textlength(texto, font=f_rotulo) / S)
    img.save(destino, optimize=True)


def main() -> None:
    xml = gerar_bpmn()
    ET.fromstring(xml)  # garante que o XML está bem formado antes de gravar
    (AQUI / "processo.bpmn").write_text(xml, encoding="utf-8")
    gerar_png(AQUI / "processo.png")
    print(f"gerados: {AQUI / 'processo.bpmn'} e {AQUI / 'processo.png'}")


if __name__ == "__main__":
    main()
