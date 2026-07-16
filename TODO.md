# TODO / Backlog

## Login social (Google / Facebook / Apple)
Entrar/cadastrar com rede social. **Complexidade média** + setup externo:
- Registrar um app em cada provedor (client id/secret), configurar a **URL de
  callback** no domínio (`/conta/entrar/<provedor>/callback`).
- Fluxo OAuth 2.0 (lib: Authlib ou Flask-Dance). Google é o mais simples;
  Facebook exige revisão do app p/ liberar e-mail; **Apple exige conta de
  desenvolvedor paga** e é o mais chato.
- Criar/associar Cliente pelo e-mail retornado (evitar duplicar cadastro).
Fazer quando tiver as contas de provedor. Por ora, login é por e-mail/CPF + senha.


## Emissão de nota fiscal (NF-e)
Etapa "Emissão de recibo" do pedido → futuramente emitir **nota fiscal**.
Precisa de integração fiscal (ex.: Focus NFe, NFE.io, PlugNotas) + dados fiscais
do ateliê. Pendente.

## Etiqueta de envio
Etapa "Pedido enviado" → gerar/imprimir **etiqueta de envio** (Correios/
transportadora, via Melhor Envio que já é usado no frete). Pendente.


## Impressora Niimbot M2 (etiquetas 50×30) — integração

**Status:** pendente (a definir). Etiqueta atual já exporta PNG e imprime pela via manual.

**Contexto:** Niimbot **não tem API/SDK oficial**. Impressão é Bluetooth (BLE) no
dispositivo — o servidor web não fala direto com a impressora. Modelo do ateliê:
**M2**, etiquetas **50×30 mm** (paisagem). A etiqueta atual do sistema é **30×50
mm** (retrato) — orientação diferente do M2.

**Caminhos possíveis:**
1. **PNG + app Niimbot (manual, já dá pra usar):** botão "Salvar imagem" da
   etiqueta → importar no app Niimbot → definir 50×30 → imprimir.
   - Falta: criar uma **variante 50×30 paisagem** da etiqueta pra sair alinhada no M2.
2. **Web Bluetooth (impressão direta do navegador):** libs da comunidade
   (não-oficiais) — **NiimBlue** (niimblue.app) / `NiimBlueLib`. Integrar um botão
   "Imprimir na Niimbot" na página da etiqueta.
   - Restrições: só **Chrome/Edge** (desktop/Android); **Safari/iOS não suportam**.
   - **Suporte ao M2 é incerto** (libs feitas p/ D11/B1/B21…). **Testar** o M2 em
     niimblue.app antes de investir.
3. **`niimprint` (Python) local no Mac** via BLE/USB. Suporte M2 a confirmar.

**Próximos passos quando retomar:**
- [ ] Criar variante **50×30 paisagem** da etiqueta (manter a 30×50 atual).
- [ ] Testar M2 em **niimblue.app** (Chrome) — confirma se dá pra impressão direta.
- [ ] Se conectar: integrar botão "Imprimir na Niimbot" (Web Bluetooth, Chrome).
