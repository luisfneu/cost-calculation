// Favoritos da vitrine (client-side, localStorage 'sh_favs'). Coração no card,
// contador no header e painel (offcanvas) com a lista. Não precisa de login.
(function () {
  const KEY = 'sh_favs';
  const fmt = v => (parseFloat(v) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });

  let favs = {};
  try { favs = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { favs = {}; }
  const salvar = () => localStorage.setItem(KEY, JSON.stringify(favs));

  const badge = document.getElementById('favs-badge');
  const vazio = document.getElementById('favs-vazio');
  const listaEl = document.getElementById('favs-lista');

  function atualizarContador() {
    const n = Object.keys(favs).length;
    if (badge) { badge.textContent = n; badge.hidden = n === 0; }
    if (vazio) vazio.hidden = n > 0;
  }

  // Marca os corações da grade conforme o estado salvo.
  function marcarCoracoes() {
    document.querySelectorAll('.js-fav').forEach(b => {
      const on = !!favs[b.dataset.id];
      b.classList.toggle('on', on);
      const ic = b.querySelector('.bi');
      if (ic) ic.className = 'bi ' + (on ? 'bi-heart-fill' : 'bi-heart');
      const txt = b.querySelector('.js-fav-txt');
      if (txt) txt.textContent = on ? 'Favorito' : 'Favoritos';
    });
  }

  function renderLista() {
    if (!listaEl) return;
    listaEl.innerHTML = '';
    Object.values(favs).forEach(it => {
      const row = document.createElement('div');
      row.className = 'fav-item';
      row.innerHTML =
        `<a href="${it.url}"><img src="${it.foto || ''}" alt="" loading="lazy"></a>`
        + `<div class="flex-grow-1"><a href="${it.url}" class="text-reset text-decoration-none">`
        + `<div class="nome"></div></a><div class="preco">${fmt(it.preco)}</div></div>`
        + `<button type="button" class="btn btn-sm btn-link text-danger p-0" data-rem="${it.id}" aria-label="Remover">`
        + `<i class="bi bi-x-lg"></i></button>`;
      row.querySelector('.nome').textContent = it.nome;   // textContent evita injeção
      listaEl.appendChild(row);
    });
  }

  // ---- Sincronização com a conta (cliente logado) ----
  // 'merge' no carregamento: une aparelho + conta (favoritos de outro celular
  // aparecem aqui). 'replace' após favoritar/remover: o aparelho manda.
  async function sincronizar(modo) {
    if (window.SH_LOGGED !== true || !window.SH_FAVS_SYNC) return;
    // Relê o localStorage antes de enviar: outras telas (ex.: página "Meus
    // favoritos") alteram a lista por fora desta cópia em memória — sem isso,
    // um 'replace' mandaria o estado velho e ressuscitaria o item removido.
    try { favs = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { /* mantém a cópia atual */ }
    try {
      const r = await fetch(window.SH_FAVS_SYNC, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Object.keys(favs), modo: modo }),
      });
      const d = await r.json();
      if (!d.ok) return;
      const faltantes = d.ids.map(String).filter(id => !favs[id]);
      if (!faltantes.length) return;
      // Busca os dados atuais das peças que só existem na conta.
      const info = await (await fetch(window.SH_PECAS_INFO + '?ids=' + faltantes.join(','))).json();
      (info.pecas || []).forEach(p => {
        favs[String(p.id)] = { id: String(p.id), nome: p.nome, preco: p.preco, foto: p.foto, url: p.url };
      });
      salvar(); atualizarContador(); marcarCoracoes(); renderLista();
      // Avisa outras telas (ex.: página "Meus favoritos") que a lista mudou.
      document.dispatchEvent(new Event('sh:favs-atualizados'));
    } catch (e) { /* offline/erro: segue só com o localStorage */ }
  }
  window.SHFavs = { sync: sincronizar };   // exposto p/ a página de favoritos

  function toggle(dados) {
    const id = dados.id;
    if (favs[id]) delete favs[id];
    else favs[id] = { id: id, nome: dados.nome, preco: dados.preco, foto: dados.foto, url: dados.url };
    salvar(); atualizarContador(); marcarCoracoes(); renderLista();
    sincronizar('replace');
  }

  // Clique no coração da grade. Visitante sem login abre modal de entrar.
  document.addEventListener('click', e => {
    const b = e.target.closest('.js-fav');
    if (!b) return;
    e.preventDefault();
    if (window.SH_LOGGED === false) {
      const el = document.getElementById('modal-login');
      if (el && window.bootstrap) { bootstrap.Modal.getOrCreateInstance(el).show(); return; }
    }
    toggle({ id: b.dataset.id, nome: b.dataset.nome, preco: b.dataset.preco, foto: b.dataset.foto, url: b.dataset.url });
  });

  // Remover pelo painel.
  if (listaEl) listaEl.addEventListener('click', e => {
    const b = e.target.closest('button[data-rem]');
    if (!b) return;
    delete favs[b.dataset.rem];
    salvar(); atualizarContador(); marcarCoracoes(); renderLista();
    sincronizar('replace');
  });

  atualizarContador(); marcarCoracoes(); renderLista();
  sincronizar('merge');   // logado: puxa os favoritos salvos na conta
})();
