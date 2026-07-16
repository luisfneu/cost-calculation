// Validador visual de senha forte. Regras: mín. 8 caracteres, 1 letra maiúscula,
// 1 caractere especial. Espelha `senha_forte()` do servidor (routes/conta.py).
//
// Uso no HTML:
//   <input type="password" data-senha-forte data-checks="#chk" data-submit="#btn">
//   <div id="chk" class="senha-checks">
//     <div class="s-chk" data-rule="len">Mínimo de 8 caracteres</div>
//     <div class="s-chk" data-rule="upper">1 letra maiúscula</div>
//     <div class="s-chk" data-rule="special">1 caractere especial, como ?-!*$#</div>
//   </div>
// Botão-olho opcional: <button data-eye="#idDaSenha">
(function () {
  const RULES = {
    len: v => v.length >= 8,
    upper: v => /[A-Z]/.test(v),
    special: v => /[^A-Za-z0-9]/.test(v),
  };

  function ligar(input) {
    const checks = input.dataset.checks ? document.querySelector(input.dataset.checks) : null;
    const submit = input.dataset.submit ? document.querySelector(input.dataset.submit) : null;
    const itens = checks ? Array.from(checks.querySelectorAll('.s-chk')) : [];

    function avaliar() {
      const v = input.value;
      let todas = true;
      itens.forEach(it => {
        const ok = (RULES[it.dataset.rule] || (() => false))(v);
        it.classList.toggle('ok', ok);
        const ic = it.querySelector('.bi');
        if (ic) ic.className = 'bi ' + (ok ? 'bi-check-circle-fill' : 'bi-circle');
        if (!ok) todas = false;
      });
      const forte = Object.values(RULES).every(fn => fn(v));
      input.setCustomValidity(forte || !v ? '' : 'Senha fraca');
      if (submit) submit.disabled = !forte;
    }

    input.addEventListener('input', avaliar);
    avaliar();
  }

  function ligarOlho(btn) {
    const alvo = document.querySelector(btn.dataset.eye);
    if (!alvo) return;
    btn.addEventListener('click', () => {
      const mostra = alvo.type === 'password';
      alvo.type = mostra ? 'text' : 'password';
      const ic = btn.querySelector('.bi');
      if (ic) ic.className = 'bi ' + (mostra ? 'bi-eye-slash' : 'bi-eye');
    });
  }

  function init() {
    document.querySelectorAll('input[data-senha-forte]').forEach(ligar);
    document.querySelectorAll('[data-eye]').forEach(ligarOlho);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
