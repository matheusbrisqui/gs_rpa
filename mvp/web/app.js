/* Passo Livre: telas do aplicativo (JavaScript puro + Leaflet). */
(() => {
  const INTERVALO_ATUALIZACAO_MS = 5000; // as telas refletem sozinhas o que a automação gravou
  const NOMES = {
    buraco: "Buraco", carro_na_calcada: "Carro na calçada", entulho_lixo: "Entulho/lixo",
    poste_obstaculo: "Poste/obstáculo", degrau_sem_rampa: "Degrau sem rampa", iluminacao: "Iluminação", outro: "Outro",
  };
  const CORES = {
    buraco: "#b3261e", carro_na_calcada: "#d97706", entulho_lixo: "#7c4a03", poste_obstaculo: "#6b21a8",
    degrau_sem_rampa: "#0e7490", iluminacao: "#ca8a04", outro: "#475569",
  };
  const SITUACOES = {
    novo: "Novo", validado: "Validado", encaminhado: "Encaminhado", resolvido: "Resolvido",
    duplicado: "Duplicado", invalido: "Inválido",
  };
  const PRIORIDADES = { alta: "Alta", media: "Média", normal: "Normal" };
  const ATIVOS = new Set(["novo", "validado", "encaminhado"]);
  const $ = (s) => document.querySelector(s);
  const texto = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- Mapa ----------
  const mapa = L.map("mapa", { zoomControl: true }).setView([-23.5612, -46.6559], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(mapa);
  const camadaRelatos = L.layerGroup().addTo(mapa);
  const camadaPontos = L.layerGroup().addTo(mapa);
  let marcadorEscolha = null;
  let escolhendoNoMapa = false;

  mapa.on("click", (e) => {
    if (!escolhendoNoMapa) return;
    const { lat, lng } = e.latlng;
    if (marcadorEscolha) marcadorEscolha.remove();
    marcadorEscolha = L.marker([lat, lng], { title: "Local escolhido" }).addTo(mapa);
    $("#lat").value = lat.toFixed(6); $("#lon").value = lng.toFixed(6);
    $("#btn-mapa-relato").setAttribute("aria-pressed", "false");
    $("#msg-relato").textContent = "Localização marcada no mapa.";
    escolhendoNoMapa = false;
  });
  $("#btn-mapa-relato").addEventListener("click", (e) => {
    escolhendoNoMapa = !escolhendoNoMapa;
    e.currentTarget.setAttribute("aria-pressed", String(escolhendoNoMapa));
    if (escolhendoNoMapa) $("#msg-relato").textContent = "Clique no mapa no local do obstáculo.";
  });

  // ---------- Abas acessíveis ----------
  const abas = [...document.querySelectorAll('[role="tab"]')];
  let abaAtual = "mapa";
  function ativarAba(aba, focar = true) {
    abas.forEach((a) => {
      const sel = a === aba;
      a.setAttribute("aria-selected", String(sel));
      a.tabIndex = sel ? 0 : -1;
      const painel = document.getElementById(a.getAttribute("aria-controls"));
      painel.hidden = !sel; painel.classList.toggle("ativo", sel);
    });
    abaAtual = aba.dataset.aba;
    // A tela de chamados é uma tabela larga: ocupa a página inteira, sem o mapa.
    document.body.classList.toggle("sem-mapa", abaAtual === "chamados");
    if (focar) aba.focus();
    if (location.hash.slice(1) !== abaAtual) history.replaceState(null, "", `#${abaAtual}`);
    if (abaAtual === "painel") carregarIndicadores();
    setTimeout(() => mapa.invalidateSize(), 50);
  }
  abas.forEach((a, i) => {
    a.addEventListener("click", () => ativarAba(a));
    a.addEventListener("keydown", (e) => {
      const dir = { ArrowRight: 1, ArrowLeft: -1, Home: -i, End: abas.length - 1 - i }[e.key];
      if (dir === undefined) return;
      e.preventDefault(); ativarAba(abas[(i + dir + abas.length) % abas.length]);
    });
  });

  // ---------- Relatos (mapa e lista) ----------
  let relatos = [], pontos = [], assinatura = null;
  async function carregarRelatos() {
    const r = await fetch("/relatos?limite=1000");
    if (!r.ok) throw new Error(r.statusText);
    const dados = await r.json();
    const nova = dados.map((x) => `${x.id}:${x.status}:${x.prioridade}:${x.protocolo}:${x.atualizado_em}`).join("|");
    const mudou = nova !== assinatura;
    relatos = dados; assinatura = nova;
    if (mudou) { desenharRelatos(); desenharChamados(); }
    return mudou;
  }
  function filtrados() {
    const tipo = $("#f-tipo").value, status = $("#f-status").value;
    return relatos.filter((x) => (!tipo || x.tipo === tipo) && (status === "ativos" ? ATIVOS.has(x.status) : !status || x.status === status));
  }
  function selos(x) {
    return `<span class="badge ${x.status}">${SITUACOES[x.status] || texto(x.status)}</span>${x.prioridade ? `<span class="badge p-${x.prioridade}">prioridade ${PRIORIDADES[x.prioridade].toLowerCase()}</span>` : ""}`;
  }
  function desenharRelatos() {
    camadaRelatos.clearLayers();
    const lista = $("#lista-relatos"); lista.innerHTML = "";
    const itens = filtrados();
    itens.forEach((x) => {
      const apagado = !ATIVOS.has(x.status);
      const m = L.circleMarker([x.lat, x.lon], {
        radius: 9, color: "#fff", weight: 2, fillColor: CORES[x.tipo] || CORES.outro, fillOpacity: apagado ? 0.35 : 0.95,
      }).bindPopup(popupRelato(x)).addTo(camadaRelatos);
      const li = document.createElement("li");
      li.innerHTML = `<i class="dot ${x.tipo}" aria-hidden="true"></i><button type="button"><span class="titulo">#${x.id} ${NOMES[x.tipo] || texto(x.tipo)}${selos(x)}</span><span class="meta">${texto(x.descricao)} · ${fmtData(x.criado_em)}${x.protocolo ? " · " + texto(x.protocolo) : ""}</span></button>`;
      li.querySelector("button").addEventListener("click", () => { mapa.setView([x.lat, x.lon], 18); m.openPopup(); });
      lista.appendChild(li);
    });
    $("#resumo-mapa").textContent = `${itens.length} relato(s) exibido(s) de ${relatos.length}. ${relatos.filter((x) => ATIVOS.has(x.status)).length} em aberto.`;
  }
  function popupRelato(x) {
    return `<strong>#${x.id} ${NOMES[x.tipo] || texto(x.tipo)}</strong> ${selos(x)}<br>${texto(x.descricao)}<br><small>Registrado em ${fmtData(x.criado_em)}${x.protocolo ? "<br>Protocolo: " + texto(x.protocolo) : ""}${x.duplicado_de ? "<br>Mesmo obstáculo do relato #" + x.duplicado_de : ""}${x.resolvido_em ? "<br>Resolvido em " + fmtData(x.resolvido_em) : ""}</small>`;
  }
  $("#f-tipo").addEventListener("change", desenharRelatos);
  $("#f-status").addEventListener("change", desenharRelatos);

  async function carregarPontos() {
    const r = await fetch("/pontos");
    if (!r.ok) throw new Error(r.statusText);
    pontos = await r.json();
    camadaPontos.clearLayers();
    pontos.forEach((p) => {
      const icone = L.divIcon({ className: "", html: '<div class="marker-ponto" aria-hidden="true">🚌</div>', iconSize: [22, 22], iconAnchor: [11, 11] });
      const acess = p.acessivel === null ? "não avaliado" : p.acessivel ? "acessível" : "não acessível";
      L.marker([p.lat, p.lon], { icon: icone, title: p.nome }).bindPopup(`<strong>${texto(p.nome)}</strong><br>${texto(p.endereco)}<br>Acesso: ${acess}<br>Obstáculos em aberto a até 60 m: <strong>${p.relatos_ativos}</strong>`).addTo(camadaPontos);
    });
  }

  // ---------- Relatar ----------
  $("#btn-geo").addEventListener("click", () => {
    const msg = $("#msg-relato");
    if (!navigator.geolocation) { msg.innerHTML = '<span class="erro">Seu navegador não oferece geolocalização.</span>'; return; }
    navigator.geolocation.getCurrentPosition(
      (p) => { $("#lat").value = p.coords.latitude.toFixed(6); $("#lon").value = p.coords.longitude.toFixed(6); msg.textContent = "Localização obtida."; },
      () => { msg.innerHTML = '<span class="erro">Não foi possível obter sua localização. Informe as coordenadas ou escolha no mapa.</span>'; },
      { timeout: 8000 },
    );
  });
  $("#form-relato").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget, msg = $("#msg-relato");
    if (!form.reportValidity()) return;
    const corpo = {
      tipo: $("#tipo").value, descricao: $("#descricao").value || null,
      lat: parseFloat($("#lat").value), lon: parseFloat($("#lon").value),
      perfil: $("#perfil").value, identificador_usuario: $("#identificador").value || null,
    };
    const btn = form.querySelector('[type="submit"]'); btn.disabled = true; msg.textContent = "Enviando…";
    try {
      const r = await fetch("/relatos", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
      if (!r.ok) throw new Error((await r.json()).detail?.[0]?.msg || r.statusText);
      const novo = await r.json();
      msg.innerHTML = `<span class="ok">Relato #${novo.id} registrado como novo.</span> A automação vai conferir, priorizar e encaminhar à prefeitura. Acompanhe na aba Chamados.`;
      form.reset();
      if (marcadorEscolha) { marcadorEscolha.remove(); marcadorEscolha = null; }
      await atualizarTudo();
      mapa.setView([novo.lat, novo.lon], 18);
    } catch (err) { msg.innerHTML = `<span class="erro">Erro ao enviar: ${texto(err.message)}</span>`; }
    finally { btn.disabled = false; }
  });

  // ---------- Chamados (resultado da automação) ----------
  function observacao(x) {
    if (x.status === "novo") return "Aguardando a automação";
    if (x.status === "duplicado") return x.duplicado_de ? `Mesmo obstáculo do relato #${x.duplicado_de}; não gerou novo chamado` : "Relato repetido";
    if (x.status === "invalido") return "Dados inconsistentes; não foi encaminhado";
    if (x.status === "resolvido") return x.resolvido_em ? `Concluído pela prefeitura em ${fmtData(x.resolvido_em)}` : "Concluído pela prefeitura";
    if (x.status === "encaminhado") return "Enviado à prefeitura";
    if (x.status === "validado") return "Conferido, em aberto";
    return "";
  }
  function desenharChamados() {
    const conta = (s) => relatos.filter((x) => x.status === s).length;
    const contadores = [
      [conta("novo"), "aguardando a automação", "novo"], [conta("encaminhado"), "encaminhados à prefeitura", "encaminhado"],
      [conta("resolvido"), "resolvidos", "resolvido"], [conta("duplicado"), "duplicados descartados", "duplicado"],
      [conta("invalido"), "inválidos", "invalido"],
    ];
    $("#contadores").innerHTML = contadores.map(([n, rotulo, s]) => `<div class="contador ${s}"><span class="n">${n}</span><span class="l">${rotulo}</span></div>`).join("");
    const filtro = $("#c-status").value;
    const itens = relatos.filter((x) => !filtro || x.status === filtro).sort((a, b) => b.id - a.id);
    $("#tabela-chamados tbody").innerHTML = itens.map((x) => `<tr>
        <th scope="row">#${x.id}</th>
        <td><i class="dot ${x.tipo}" aria-hidden="true"></i>${NOMES[x.tipo] || texto(x.tipo)}</td>
        <td><span class="badge ${x.status}">${SITUACOES[x.status] || texto(x.status)}</span></td>
        <td>${x.prioridade ? `<span class="badge p-${x.prioridade}">${PRIORIDADES[x.prioridade]}</span>` : "—"}</td>
        <td class="protocolo">${x.protocolo ? texto(x.protocolo) : "—"}</td>
        <td>${observacao(x)}</td>
        <td>${fmtData(x.criado_em)}</td>
        <td>${fmtData(x.atualizado_em, true)}</td>
      </tr>`).join("") || '<tr><td colspan="8">Nenhum relato nesta situação.</td></tr>';
  }
  $("#c-status").addEventListener("change", desenharChamados);
  $("#btn-atualizar").addEventListener("click", atualizarTudo);

  // ---------- Painel ----------
  async function carregarIndicadores() {
    const r = await fetch("/indicadores");
    if (!r.ok) return;
    const d = await r.json();
    const cards = [
      [d.total_relatos, "relatos registrados"], [d.aguardando_triagem, "aguardando a automação"],
      [d.triados_pela_automacao, "já triados"], [d.relatos_resolvidos, "resolvidos"],
      [d.tempo_medio_resolucao_dias ?? "—", "dias até resolver (média)"],
      [`${d.pontos_onibus_com_obstaculo_ativo}/${d.pontos_onibus_total}`, "pontos de ônibus com obstáculo em aberto"],
    ];
    $("#cards").innerHTML = cards.map(([n, l]) => `<div class="card"><span class="n">${n}</span><span class="l">${l}</span></div>`).join("");
    barras("#barras-status", d.relatos_por_status, (k) => SITUACOES[k] || k);
    barras("#barras-prioridade", d.relatos_por_prioridade, (k) => PRIORIDADES[k] || k);
    barras("#barras-tipo", d.relatos_por_tipo, (k) => NOMES[k] || k);
    $("#gerado-em").textContent = `Atualizado em ${fmtData(d.gerado_em, true)}.`;
  }
  function barras(sel, obj, rotulo) {
    const max = Math.max(1, ...Object.values(obj));
    $(sel).innerHTML = Object.entries(obj).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<div class="barra"><span>${rotulo(k)}</span><div class="track" role="img" aria-label="${rotulo(k)}: ${v}"><div class="fill" style="width:${(100 * v) / max}%"></div></div><strong>${v}</strong></div>`).join("") || '<p class="info">Sem dados.</p>';
  }

  // ---------- Atualização ----------
  function fmtData(iso, hora = false) {
    const d = new Date(iso);
    return d.toLocaleDateString("pt-BR") + (hora ? " " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
  }
  async function atualizarTudo() {
    const aviso = $("#atualizado-chamados");
    try {
      const mudou = await carregarRelatos();
      if (mudou) { await carregarPontos(); if (abaAtual === "painel") await carregarIndicadores(); }
      aviso.textContent = `Atualização automática a cada ${INTERVALO_ATUALIZACAO_MS / 1000} segundos. Última consulta: ${new Date().toLocaleTimeString("pt-BR")}.`;
    } catch (err) {
      aviso.innerHTML = `<span class="erro">Sem conexão com o servidor (${texto(err.message)}). Tentando de novo.</span>`;
    }
  }

  // O endereço guarda a aba aberta (ex.: /#chamados), para abrir direto nela e usar o botão voltar.
  function abrirAbaDoEndereco() {
    const aba = abas.find((a) => a.dataset.aba === location.hash.slice(1));
    if (aba && aba.dataset.aba !== abaAtual) ativarAba(aba, false);
  }
  window.addEventListener("hashchange", abrirAbaDoEndereco);
  abrirAbaDoEndereco();
  atualizarTudo();
  setInterval(atualizarTudo, INTERVALO_ATUALIZACAO_MS);
})();
