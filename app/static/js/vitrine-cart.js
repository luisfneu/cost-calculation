// Carrinho da vitrine (client-side, localStorage). Portado da vitrine V1 para ser
// reutilizável. Configuração vem de window.SH_CART:
//   { whats, cliente, urls:{frete,cupom,pedido}, contaSair }
// Markup: _carrinho.html. Estilos: estilo.css. Seguro em páginas sem o carrinho.
(function () {
  const cfg = window.SH_CART || {};
  if (!document.getElementById('sh-cart')) return;   // página sem carrinho: não faz nada

  const WHATS = cfg.whats || '';
  const CLIENTE = cfg.cliente || null;
  const URLS = cfg.urls || {};
  const KEY = 'sh_cart_v1';
  const fmt = v => (v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  let cart = {};
  try { cart = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { cart = {}; }

  const badge = document.getElementById('cart-badge');
  const vazio = document.getElementById('cart-vazio');
  const rodape = document.getElementById('cart-rodape');
  const lista = document.getElementById('cart-itens');
  const totalEl = document.getElementById('cart-total');
  const subEl = document.getElementById('cart-subtotal');
  const cupomEl = document.getElementById('cart-cupom');
  const fab = document.querySelector('.vitrine-cart-fab');
  const cepEl = document.getElementById('cart-cep');
  const calcBtn = document.getElementById('cart-calc-frete');
  const opcoesEl = document.getElementById('cart-frete-opcoes');
  const freteMsg = document.getElementById('cart-frete-msg');
  const freteLinha = document.getElementById('cart-frete-linha');
  const freteNome = document.getElementById('cart-frete-nome');
  const freteValor = document.getElementById('cart-frete-valor');
  const cupomBtn = document.getElementById('cart-aplicar-cupom');
  const cupomMsg = document.getElementById('cart-cupom-msg');
  const descLinha = document.getElementById('cart-desconto-linha');
  const descNome = document.getElementById('cart-desconto-nome');
  const descValor = document.getElementById('cart-desconto-valor');

  let frete = null, cupom = null, opcoesFrete = [];
  let retiradaLiberada = false;   // "Retirar em mãos" só após calcular e se o CEP for RS
  try { frete = JSON.parse(localStorage.getItem(KEY + '_frete')) || null; } catch (e) { frete = null; }
  try { cupom = JSON.parse(localStorage.getItem(KEY + '_cupomobj')) || null; } catch (e) { cupom = null; }

  function animarCarrinho() {
    if (!fab) return;
    fab.classList.remove('cart-pulou'); void fab.offsetWidth; fab.classList.add('cart-pulou');
  }

  const cartEl = document.getElementById('sh-cart');
  let cartTimer = null;
  function abrirCarrinhoBreve() {
    if (!cartEl || !window.bootstrap) return;
    const oc = bootstrap.Offcanvas.getOrCreateInstance(cartEl);
    oc.show();
    if (cartTimer) clearTimeout(cartTimer);
    cartTimer = setTimeout(() => { oc.hide(); cartTimer = null; }, 5000);
  }
  if (cartEl) {
    const cancelar = () => { if (cartTimer) { clearTimeout(cartTimer); cartTimer = null; } };
    ['mouseenter', 'pointerdown', 'focusin', 'touchstart'].forEach(ev => cartEl.addEventListener(ev, cancelar));
    cartEl.addEventListener('hidden.bs.offcanvas', cancelar);
  }

  function mascararCep() {
    const d = cepEl.value.replace(/\D/g, '').slice(0, 8);
    cepEl.value = d.length > 5 ? d.slice(0, 5) + '-' + d.slice(5) : d;
    localStorage.setItem(KEY + '_cep', cepEl.value);
  }
  async function buscarCepEndereco() {
    const d = cepEl.value.replace(/\D/g, '');
    const status = document.getElementById('cart-cep-status');
    if (d.length !== 8) { status.textContent = ''; return; }
    status.textContent = '…'; status.className = 'small text-muted';
    try {
      const resp = await fetch(`https://viacep.com.br/ws/${d}/json/`);
      const dados = await resp.json();
      if (dados.erro) { status.textContent = '✗'; status.className = 'small text-danger'; return; }
      const set = (k, v) => { const el = document.getElementById('pc-' + k); if (el && v) { el.value = v; localStorage.setItem(KEY + '_pc_' + k, v); } };
      set('logradouro', dados.logradouro); set('bairro', dados.bairro);
      set('cidade', dados.localidade); set('uf', dados.uf);
      status.textContent = '✓'; status.className = 'small text-success';
      const num = document.getElementById('pc-numero');
      if (num && !document.getElementById('cart-form').hidden) num.focus();
    } catch (e) { status.textContent = ''; }
  }
  cepEl.value = localStorage.getItem(KEY + '_cep') || '';
  cepEl.addEventListener('input', () => { mascararCep(); if (cepEl.value.replace(/\D/g, '').length === 8) buscarCepEndereco(); });
  cepEl.addEventListener('blur', buscarCepEndereco);
  mascararCep();
  cupomEl.value = localStorage.getItem(KEY + '_cupom') || '';
  cupomEl.addEventListener('input', () => localStorage.setItem(KEY + '_cupom', cupomEl.value));

  const salvar = () => localStorage.setItem(KEY, JSON.stringify(cart));
  const salvarFreteCupom = () => {
    localStorage.setItem(KEY + '_frete', JSON.stringify(frete));
    localStorage.setItem(KEY + '_cupomobj', JSON.stringify(cupom));
  };
  const subtotalAtual = () => Object.values(cart).reduce((s, it) => s + it.qtd * it.preco, 0);
  const descontoAtual = () => {
    if (!cupom || cupom.tipo === 'frete') return 0;
    const sub = subtotalAtual();
    const d = cupom.tipo === 'percentual' ? sub * cupom.valor / 100 : Math.min(cupom.valor, sub);
    return Math.round(d * 100) / 100;
  };
  const descontoFreteAtual = () => {
    if (!cupom || cupom.tipo !== 'frete') return 0;
    const freteAtual = frete ? (parseFloat(frete.preco) || 0) : 0;
    if (!freteAtual) return 0;
    const limite = cupom.valor > 0 ? cupom.valor : freteAtual;
    return Math.round(Math.min(limite, freteAtual) * 100) / 100;
  };
  function limparFrete() { frete = null; opcoesFrete = []; retiradaLiberada = false; salvarFreteCupom(); renderFreteOpcoes(); freteMsg.textContent = ''; }

  function renderFreteOpcoes() {
    opcoesEl.innerHTML = '';
    // "Retirar em mãos" só entra quando o CEP calculado é de RS.
    const opts = (retiradaLiberada ? [{ nome: 'Retirar em mãos', preco: 0, prazo: null, retirar: true }] : []).concat(opcoesFrete);
    if (!opts.length) {
      opcoesEl.innerHTML = '<div class="small text-muted">Informe seu CEP e clique em <strong>Calcular</strong>.</div>';
      return;
    }
    // Depois de escolher, mostra só a opção selecionada (+ "trocar frete").
    const mostrar = frete ? opts.filter(o => o.nome === frete.nome) : opts;
    mostrar.forEach(o => {
      const preco = parseFloat(o.preco) || 0;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'frete-opcao' + (frete && frete.nome === o.nome ? ' sel' : '');
      b.innerHTML = `<span>${o.nome}${o.rapido ? ' <span class="frete-rapido">mais rápido</span>' : ''}`
        + `<small>${o.retirar ? 'sem custo de envio' : (o.prazo ? o.prazo + ' dia(s)' : '')}</small></span>`
        + `<strong>${preco ? fmt(preco) : 'Grátis'}</strong>`;
      b.addEventListener('click', () => {
        frete = { nome: o.nome, preco: preco, prazo: o.prazo || null, retirar: !!o.retirar };
        salvarFreteCupom(); renderFreteOpcoes(); render();
      });
      opcoesEl.appendChild(b);
    });
    if (frete && opts.length > 1) {
      const trocar = document.createElement('button');
      trocar.type = 'button';
      trocar.className = 'btn btn-link btn-sm p-0 mt-1 text-muted';
      trocar.innerHTML = '<i class="bi bi-arrow-repeat"></i> trocar frete';
      trocar.addEventListener('click', () => { frete = null; salvarFreteCupom(); renderFreteOpcoes(); render(); });
      opcoesEl.appendChild(trocar);
    }
  }

  function render() {
    let qtdTotal = 0, valorTotal = 0;
    lista.innerHTML = '';
    Object.keys(cart).forEach(key => {
      const it = cart[key];
      qtdTotal += it.qtd; valorTotal += it.qtd * it.preco;
      const row = document.createElement('div'); row.className = 'cart-item';
      const thumb = document.createElement('img'); thumb.className = 'cart-item-thumb'; thumb.alt = ''; thumb.loading = 'lazy';
      if (it.foto) { thumb.src = it.foto; } else { thumb.classList.add('sem-foto'); }
      const info = document.createElement('div'); info.className = 'cart-item-info';
      const nome = document.createElement('div'); nome.className = 'cart-item-nome';
      nome.textContent = it.nome + (it.tam ? ' · ' + it.tam : '');
      const preco = document.createElement('div'); preco.className = 'cart-item-preco';
      preco.textContent = fmt(it.preco) + (it.encomenda ? ' · sob encomenda' : '');
      info.append(nome, preco);
      const ctrl = document.createElement('div'); ctrl.className = 'cart-qtd';
      ctrl.innerHTML = `<button type="button" data-act="menos" data-key="${key}" aria-label="Menos">−</button>`
        + `<span>${it.qtd}</span>`
        + `<button type="button" data-act="mais" data-key="${key}" aria-label="Mais">+</button>`;
      row.append(thumb, info, ctrl);
      lista.appendChild(row);
    });
    badge.textContent = qtdTotal; badge.hidden = qtdTotal === 0;
    vazio.hidden = qtdTotal > 0; rodape.hidden = qtdTotal === 0;
    const freteValorNum = frete ? (parseFloat(frete.preco) || 0) : 0;
    const descNum = descontoAtual(), descFreteNum = descontoFreteAtual();
    subEl.textContent = fmt(valorTotal);
    if (cupom && (descNum > 0 || descFreteNum > 0)) {
      descLinha.hidden = false;
      descNome.textContent = cupom.codigo + (descFreteNum > 0 ? ' (frete)' : '');
      descValor.textContent = '−' + fmt(descNum || descFreteNum);
    } else { descLinha.hidden = true; }
    if (frete) {
      freteLinha.hidden = false;
      freteNome.textContent = frete.nome + (frete.prazo ? ` · ${frete.prazo} dia(s)` : '');
      const freteFinal = Math.max(0, freteValorNum - descFreteNum);
      freteValor.textContent = freteFinal ? fmt(freteFinal) : 'Grátis';
    } else { freteLinha.hidden = true; }
    totalEl.textContent = fmt(Math.max(0, valorTotal - descNum) + Math.max(0, freteValorNum - descFreteNum));
  }

  function add(dados) {
    const key = dados.id + '|' + dados.tam;
    if (!cart[key]) cart[key] = Object.assign({ qtd: 0 }, dados);
    cart[key].qtd++;
    limparFrete(); salvar(); render(); animarCarrinho(); abrirCarrinhoBreve();
  }
  function mudar(key, delta) {
    if (!cart[key]) return;
    cart[key].qtd += delta;
    if (cart[key].qtd <= 0) delete cart[key];
    limparFrete(); salvar(); render();
  }
  window.SHCart = { add };   // exposto para páginas que adicionam ao pedido

  function itensParaFrete() { return Object.values(cart).map(it => ({ id: it.id, qtd: it.qtd })); }
  calcBtn.addEventListener('click', async () => {
    const cep = (cepEl.value || '').replace(/\D/g, '');
    if (cep.length !== 8) { freteMsg.textContent = 'Informe um CEP válido (8 dígitos).'; return; }
    if (!Object.keys(cart).length) { freteMsg.textContent = 'Seu pedido está vazio.'; return; }
    calcBtn.disabled = true; freteMsg.textContent = 'Calculando…';
    // Libera "Retirar em mãos" apenas se o CEP for de RS (ateliê é em RS).
    retiradaLiberada = false;
    try {
      const vc = await (await fetch(`https://viacep.com.br/ws/${cep}/json/`)).json();
      retiradaLiberada = ((vc.uf || '').toUpperCase() === 'RS');
    } catch (e) { /* sem UF: mantém retirada bloqueada */ }
    fetch(URLS.frete, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cep: cep, itens: itensParaFrete() }) })
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok || !d.ok) { freteMsg.textContent = d.erro || 'Não foi possível calcular o frete.'; return; }
        freteMsg.textContent = d.opcoes.length ? '' : 'Nenhuma opção de frete para este CEP (mas você pode retirar em mãos).';
        opcoesFrete = d.opcoes; renderFreteOpcoes();
      })
      .catch(() => { freteMsg.textContent = 'Falha de conexão ao calcular o frete.'; })
      .finally(() => { calcBtn.disabled = false; });
  });

  cupomBtn.addEventListener('click', () => {
    const cod = (cupomEl.value || '').trim().toUpperCase();
    cupomMsg.className = 'small mb-2';
    if (!cod) { cupom = null; salvarFreteCupom(); cupomMsg.textContent = ''; render(); return; }
    if (!Object.keys(cart).length) { cupomMsg.textContent = 'Seu pedido está vazio.'; return; }
    cupomBtn.disabled = true; cupomMsg.textContent = 'Validando…';
    fetch(URLS.cupom, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codigo: cod, subtotal: subtotalAtual() }) })
      .then(r => r.json())
      .then(d => {
        if (!d.ok) {
          cupom = null; salvarFreteCupom();
          cupomMsg.className = 'small mb-2 ' + (d.pessoal ? 'text-warning' : 'text-danger');
          cupomMsg.textContent = d.erro || 'Cupom inválido.';
        } else {
          cupom = { codigo: d.codigo, tipo: d.tipo, valor: d.valor };
          salvarFreteCupom(); localStorage.setItem(KEY + '_cupom', d.codigo);
          cupomMsg.className = 'small mb-2 text-success';
          cupomMsg.textContent = `Cupom ${d.codigo} aplicado (${d.rotulo}).`;
        }
        render();
      })
      .catch(() => { cupomMsg.className = 'small mb-2 text-danger'; cupomMsg.textContent = 'Falha ao validar o cupom.'; })
      .finally(() => { cupomBtn.disabled = false; });
  });

  lista.addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (btn) mudar(btn.dataset.key, btn.dataset.act === 'mais' ? 1 : -1);
  });

  document.getElementById('cart-limpar').addEventListener('click', () => {
    cart = {}; cupom = null; cupomEl.value = ''; cupomMsg.textContent = '';
    localStorage.removeItem(KEY + '_cupom'); limparFrete(); salvar(); render();
  });

  document.getElementById('cart-enviar').addEventListener('click', () => {
    const chaves = Object.keys(cart);
    if (!chaves.length) return;
    const linhas = ['Olá! Gostaria de fazer um pedido pela vitrine:', ''];
    let subtotal = 0;
    chaves.forEach(key => {
      const it = cart[key]; subtotal += it.qtd * it.preco;
      const tam = it.tam ? ` (${it.tam})` : '', enc = it.encomenda ? ' [sob encomenda]' : '';
      linhas.push(`• ${it.qtd}x ${it.nome}${tam}${enc} — ${fmt(it.qtd * it.preco)}`);
    });
    linhas.push('', `Subtotal: ${fmt(subtotal)}`);
    const desc = descontoAtual();
    if (cupom && desc > 0) linhas.push(`Cupom ${cupom.codigo}: −${fmt(desc)}`);
    const freteNum = frete ? (parseFloat(frete.preco) || 0) : 0;
    if (frete) {
      const detalhe = frete.retirar ? 'retirar em mãos' : `${frete.nome}${frete.prazo ? ', ' + frete.prazo + ' dia(s)' : ''}`;
      linhas.push(`Frete (${detalhe}): ${freteNum ? fmt(freteNum) : 'grátis'}`);
    }
    const cep = (cepEl.value || '').trim();
    if (cep && !(frete && frete.retirar)) linhas.push(`CEP de entrega: ${cep}`);
    linhas.push(`Total: ${fmt(Math.max(0, subtotal - desc) + freteNum)}`);
    window.open(`https://wa.me/${WHATS}?text=` + encodeURIComponent(linhas.join('\n')), '_blank');
  });

  // ---- Pré-cadastro + envio do pedido (cria um Lead no ateliê) ----
  const formEl = document.getElementById('cart-form');
  const sucessoEl = document.getElementById('cart-sucesso');
  const pcCampos = ['nome', 'whats', 'insta', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'uf'];
  const pcEl = id => document.getElementById('pc-' + id);
  const pcMsg = document.getElementById('pc-msg');
  let ultimoEnvio = null;

  pcCampos.forEach(k => {
    const el = pcEl(k);
    el.value = localStorage.getItem(KEY + '_pc_' + k) || '';
    el.addEventListener('input', () => localStorage.setItem(KEY + '_pc_' + k, el.value));
  });

  function prefillCliente() {
    const banner = document.getElementById('pc-conta-banner');
    const cta = document.getElementById('pc-conta-cta');
    if (!CLIENTE) { if (cta) cta.hidden = false; return; }
    const set = (id, v) => { const el = pcEl(id); if (el && v && !el.value) el.value = v; };
    set('nome', CLIENTE.nome); set('whats', CLIENTE.telefone); set('insta', CLIENTE.instagram);
    set('logradouro', CLIENTE.logradouro); set('numero', CLIENTE.numero);
    set('complemento', CLIENTE.complemento); set('bairro', CLIENTE.bairro);
    set('cidade', CLIENTE.cidade); set('uf', CLIENTE.uf);
    if (CLIENTE.cep && !cepEl.value) { cepEl.value = CLIENTE.cep; mascararCep(); }
    if (banner) {
      banner.innerHTML = '<i class="bi bi-person-check"></i> Comprando como <strong>'
        + CLIENTE.nome + '</strong> · <a href="' + (cfg.contaSair || '#') + '">não é você?</a>';
      banner.hidden = false;
    }
    if (cta) cta.hidden = true;
  }
  prefillCliente();

  document.getElementById('cart-abrir-form').addEventListener('click', () => {
    if (!Object.keys(cart).length) return;
    formEl.hidden = !formEl.hidden;
    if (!formEl.hidden) { prefillCliente(); formEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
  });

  function dadosCliente() {
    return {
      nome: pcEl('nome').value.trim(), telefone: pcEl('whats').value.trim(),
      instagram: pcEl('insta').value.trim(), cep: cepEl.value.trim(),
      logradouro: pcEl('logradouro').value.trim(), numero: pcEl('numero').value.trim(),
      complemento: pcEl('complemento').value.trim(), bairro: pcEl('bairro').value.trim(),
      cidade: pcEl('cidade').value.trim(), uf: pcEl('uf').value.trim(),
    };
  }

  document.getElementById('cart-enviar-pedido').addEventListener('click', () => {
    const cli = dadosCliente();
    pcMsg.className = 'small mb-2';
    if (!cli.nome) { pcMsg.className = 'small mb-2 text-danger'; pcMsg.textContent = 'Informe seu nome.'; return; }
    if (cli.telefone.replace(/\D/g, '').length < 10) { pcMsg.className = 'small mb-2 text-danger'; pcMsg.textContent = 'Informe um WhatsApp válido com DDD.'; return; }
    const btn = document.getElementById('cart-enviar-pedido');
    btn.disabled = true; pcMsg.textContent = 'Enviando…';
    fetch(URLS.pedido, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cliente: cli,
        itens: Object.values(cart).map(it => ({ id: it.id, tam: it.tam, qtd: it.qtd })),
        frete: frete ? { nome: frete.nome, preco: frete.preco } : null,
        cupom: cupom ? { codigo: cupom.codigo } : null,
      }) })
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok || !d.ok) { pcMsg.className = 'small mb-2 text-danger'; pcMsg.textContent = d.erro || 'Não foi possível enviar o pedido.'; return; }
        ultimoEnvio = { resumo: d.resumo, whatsapp: d.whatsapp, pix: d.pix, nome: cli.nome };
        cart = {}; cupom = null; salvar(); salvarFreteCupom();
        formEl.hidden = true;
        document.getElementById('cart-itens').innerHTML = '';
        rodape.hidden = true;
        document.getElementById('cart-rodape-obs').hidden = true;
        const pixWrap = document.getElementById('pc-pix-wrap');
        if (d.pix) { document.getElementById('pc-pix').value = d.pix; pixWrap.hidden = false; } else { pixWrap.hidden = true; }
        sucessoEl.hidden = false;
        render(); abrirWhats();
      })
      .catch(() => { pcMsg.className = 'small mb-2 text-danger'; pcMsg.textContent = 'Falha de conexão.'; })
      .finally(() => { btn.disabled = false; });
  });

  function abrirWhats() {
    if (!ultimoEnvio || !ultimoEnvio.whatsapp) return;
    const msg = `Olá! Acabei de enviar um pedido pela vitrine (${ultimoEnvio.nome}):\n\n${ultimoEnvio.resumo}`;
    window.open(`https://wa.me/${ultimoEnvio.whatsapp}?text=` + encodeURIComponent(msg), '_blank');
  }
  document.getElementById('pc-abrir-whats').addEventListener('click', abrirWhats);
  document.getElementById('pc-pix-copiar').addEventListener('click', () => {
    const t = document.getElementById('pc-pix');
    t.select(); navigator.clipboard && navigator.clipboard.writeText(t.value);
    document.getElementById('pc-pix-copiar').innerHTML = '<i class="bi bi-check2"></i> Copiado!';
  });
  document.getElementById('pc-novo').addEventListener('click', () => {
    sucessoEl.hidden = true; document.getElementById('cart-rodape-obs').hidden = false; render();
  });

  if (frete) {
    if (frete.retirar) retiradaLiberada = true;                 // retirada já escolhida antes
    else opcoesFrete = [{ nome: frete.nome, preco: frete.preco, prazo: frete.prazo }];
  }
  renderFreteOpcoes();   // sem cálculo prévio: só mostra a dica "informe o CEP"
  render();
})();
