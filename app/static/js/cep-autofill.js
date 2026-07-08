// Autopreenche o endereço pelo CEP (ViaCEP) — mesma lógica da vitrine.
// Opt-in: marque o input do CEP com `data-cep-autofill`. Os campos preenchidos
// são buscados dentro do mesmo <form> pelos names: logradouro, bairro, cidade, uf
// (numero recebe o foco). Um <span data-cep-status> ao lado mostra …/✓/✗.
(function () {
  const digits = (s) => (s || "").replace(/\D/g, "");

  function mascarar(el) {
    const d = digits(el.value).slice(0, 8);
    el.value = d.length > 5 ? d.slice(0, 5) + "-" + d.slice(5) : d;
  }

  async function buscar(el) {
    const d = digits(el.value);
    const form = el.closest("form") || document;
    const status = el.parentElement.querySelector("[data-cep-status]");
    if (d.length !== 8) { if (status) status.textContent = ""; return; }
    if (status) { status.textContent = "…"; status.className = "small text-muted"; }
    try {
      const resp = await fetch(`https://viacep.com.br/ws/${d}/json/`);
      const dados = await resp.json();
      if (dados.erro) {
        if (status) { status.textContent = "✗"; status.className = "small text-danger"; }
        return;
      }
      // Campos derivados do CEP: sempre atualiza (numero/complemento são do cliente).
      const set = (name, val) => {
        const t = form.querySelector(`[name="${name}"]`);
        if (t && val) t.value = val;
      };
      set("logradouro", dados.logradouro);
      set("bairro", dados.bairro);
      set("cidade", dados.localidade);
      set("uf", dados.uf);
      if (status) { status.textContent = "✓"; status.className = "small text-success"; }
      const num = form.querySelector('[name="numero"]');
      if (num && !num.value) num.focus();
    } catch (e) {
      if (status) status.textContent = "";  // sem conexão: preenche manualmente
    }
  }

  document.querySelectorAll("input[data-cep-autofill]").forEach((el) => {
    mascarar(el);
    el.addEventListener("input", () => {
      mascarar(el);
      if (digits(el.value).length === 8) buscar(el);
    });
    el.addEventListener("blur", () => buscar(el));
  });
})();
