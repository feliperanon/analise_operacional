# Inteligência operacional — BI Clientes (`/bi/clientes`)

Documentação curta das regras de decisão da página para manutenção, alinhamento com a diretoria e calibração dos limiares. A lógica vive principalmente em `bi_clientes_intel.py` e no dataset montado em `bi_delivery_routes.py` (`_build_bi_clientes_dataset`).

---

## 1. Objetivo da página

A rota **`/bi/clientes`** funciona como **central de decisão por cliente**: consolida sinais do período e dos filtros atuais para apoiar ação operacional e comercial.

A página destaca, entre outros:

- **Clientes críticos** — perfil e volume que exigem plano de ataque.
- **Clientes bons** — carteira estável ou premium operacional para referência.
- **Alto valor com risco** — relevância de faturamento com índice de devolução acima da referência.
- **Pequenos com alto impacto** — baixo retorno relativo com custo operacional ou devolução desproporcional.
- **Impacto evitável** — valor ligado a motivos tratáveis (pedido, pagamento, ausência, horário, etc.).
- **Motivo dominante de devolução** — leitura do que mais pesa no recorte.
- **Responsabilidade dominante** — agregação em **Comercial**, **Logística**, **Mercado** ou **Sem classificação**, conforme o mapeamento por motivo (ver secção 4).

---

## 2. Meta principal

A **meta de devolução sobre base comercial** usada na faixa de período é **2%** (valor alinhado a `RETURN_RATE_TARGET` em `bi_clientes_intel.py`).

**Faixas do índice global de devolução (resumo do período):**

| Faixa     | Regra                          |
|----------|---------------------------------|
| **OK**   | índice ≤ 2%                    |
| **Atenção** | índice > 2% e ≤ 3%         |
| **Crítico** | índice > 3%                |

Os limites 2% e 3% correspondem a `RETURN_RATE_TARGET` e `RETURN_RATE_ATTENTION_MAX` (o código interno também usa pontos percentuais, ex.: `2.0` = 2%).

---

## 3. Resumo do período (`decision_strip`)

A faixa **“Resumo do período”** consome o objeto `decision_strip` gerado por `build_decision_strip_intel`. Em geral apresenta:

- **Situação do período** — OK, Atenção ou Crítico (rótulo e dica operacional).
- **Índice atual** e **diferença para a meta** (em pontos percentuais).
- **Valor devolvido** total no recorte.
- **Impacto evitável** (valor tratável agregado).
- **Motivo líder** e **responsabilidade dominante** (texto de apoio vindo da agregação por valor devolvido).

**Alerta secundário (`secondary_note`):** mensagem extra quando há, por exemplo, muito valor tratável mesmo com período “OK”, ou muitos clientes críticos na carteira. **Não altera** a classificação principal (OK / Atenção / Crítico); apenas informa um segundo foco de atenção.

---

## 4. Responsabilidade operacional por motivo

O agrupamento é feito pela função `dominio_operacional_por_motivo` (normalização em minúsculas e correspondência por trechos do texto do motivo). A lista abaixo resume o **espírito** das regras; o código inclui **sinônimos e variações** (ex.: “não entregue”, “pedido errado”, fechado/ausente, etc.).

**Comercial (exemplos):**

- Pedido / produto errado  
- Preço errado  
- Prazo errado  
- Forma de pagamento errada  
- Cliente não fez pedido / não solicitou  

**Logística (exemplos):**

- Caminhão quebrado na rota  
- Pedido não entregue  
- Produto danificado e/ou falta de produto  
- Avaria, separação ou conferência errada (quando o texto indica operação de carga/separação)  

**Mercado (exemplos):**

- Ponto de venda fechado / cliente ausente  
- Sem dinheiro / cheque  
- Cliente desistiu da compra  

**Sem classificação:**

- Motivo vazio ou “não informado”  
- Motivo que não casa com os padrões acima  
- **Horário de entrega ambíguo** — quando o texto fala de horário sem deixar claro se o driver é Mercado ou Logística (regra explícita no código)  

Para a faixa de período, a **responsabilidade dominante** exibida junto ao resumo vem da soma do valor devolvido por domínio (`dominante_operacional_por_valor_devolvido`).

---

## 5. O que fazer primeiro

A recomendação principal (**“O que fazer primeiro”**) é calculada por `primeira_acao_prioridade_sp`, nesta **ordem de prioridade**:

1. **Impacto evitável alto** — valor e participação de devolução tratável acima dos limiares (`FIRST_ACTION_TREATABLE_*`).  
2. **Muitos clientes críticos** — carteira mínima e contagem de críticos acima do limiar dinâmico (`FIRST_ACTION_CRITICAL_*`).  
3. **Grandes clientes com risco** — contagem de “grandes com risco” vs. tamanho da carteira (`FIRST_ACTION_LARGE_RISK_*`).  
4. **Pequenos com alto impacto** — mesma ideia com `FIRST_ACTION_SMALL_HIGH_*`.  
5. **Fallback** — recomendação neutra já vinda do pipeline (ex.: primeira linha de `recommendations`) ou texto padrão de acompanhamento.

---

## 6. Rankings (abas)

As abas de ranking no front correspondem a chaves em `client_ranking_tabs` / `client_ranking_tabs_json`:

| Aba | Função |
|-----|--------|
| **Maior compra** | Maior valor entregue. |
| **Maior devolução** | Maior valor devolvido. |
| **Maior % devolução** | Maior índice percentual entre clientes com **volume entregue suficiente** (evita micro-cliente distorcendo o ranking). |
| **Baixo volume · distorção %** | Clientes com entregue abaixo do piso e percentual de devolução alto — leitura à parte do ranking principal de %. |
| **Maior tempo** | Prioriza tempo médio e máximo de parada. |
| **Grandes com risco** | Cliente “grande” (piso em R$ entregue vs. percentil da carteira, ver constantes `LARGE_RISK_*`) com taxa de devolução acima do mínimo configurado. |
| **Melhores clientes** | Bom volume relativo, índice de devolução controlado, score mínimo e tempo médio favorável (`BEST_CLIENT_*`). |
| **Pequeno com alto impacto** | Alinhado ao recorte de alto impacto operacional (mesma família de dados dos “pequenos com alto impacto”). |

**Regra importante:** clientes de **muito baixo volume** não devem dominar o ranking principal de **% devolução**; por isso existe piso em `MIN_VOLUME_ENTREGUE_PAR_RANKING_PCT_BRL` e uma aba dedicada para distorção em baixo volume.

---

## 7. Constantes de calibração (`bi_clientes_intel.py`)

No **topo** do arquivo ficam os limiares nomeados. Resumo do que cada grupo **controla**:

| Grupo / constantes | O que calibra |
|--------------------|----------------|
| `RETURN_RATE_TARGET` | Meta principal de devolução (fração; hoje 2%). Alimenta `META_DEVOLUCAO_VALOR_PCT` em pontos %. |
| `RETURN_RATE_ATTENTION_MAX` (+ `DECISION_ATTENTION_MAX_PCT_POINTS`) | Teto da faixa **Atenção** (hoje 3%) e textos que citam “patamar de atenção”. |
| `TREATABLE_*` | Texto especial na faixa Atenção e alerta secundário em período OK quando há muito valor tratável. |
| `CRITICAL_*` | Alertas secundários de “muitos críticos” em período OK ou Atenção (carteira mínima, share e pisos). |
| `FIRST_ACTION_*` | Ordem e gatilhos da recomendação **“O que fazer primeiro”** (tratável, críticos, grandes com risco, pequeno alto impacto). |
| `MIN_VOLUME_ENTREGUE_PAR_RANKING_PCT_BRL` | Piso de R$ entregue para entrar no ranking principal de **% devolução**. |
| `LOW_VOLUME_DISTORTION_*` | Quem entra na aba **Baixo volume · distorção %** (teto de entregue + % mínimo de devolução). |
| `LARGE_RISK_*` | Definição de “grande com risco”: piso financeiro combinado com P75 e taxa mínima de devolução. |
| `BEST_CLIENT_*` | Quem aparece em **Melhores clientes** (teto de % devolução, score, tempo vs. média e fallback em minutos). |
| `KPI_RETURN_RATE_*` | Limiares das **cores** do KPI de índice de devolução no template (verde / amarelo / vermelho), espelhados em pontos % no dataset (`executive_kpis`). |

---

## 8. Como calibrar em reunião

Altere **apenas as constantes** no topo de `bi_clientes_intel.py` sempre que possível; evite espalhar números mágicos no restante do código.

**Exemplos práticos:**

- **Mudar a meta de 2% para outro valor** — ajustar `RETURN_RATE_TARGET` (tudo que depende de `META_DEVOLUCAO_VALOR_PCT` acompanha, inclusive classificações que usam essa referência).  
- **Deixar o “Crítico” mais rígido ou mais flexível** — ajustar `RETURN_RATE_ATTENTION_MAX` (e, se necessário, alinhar textos que mencionam percentuais).  
- **Subir o piso de “cliente relevante” de R$ 2.500 para R$ 3.000** — atualizar `LARGE_RISK_MIN_DELIVERED_FLOOR_BRL`; para o ranking de % e baixo volume, avaliar também `MIN_VOLUME_ENTREGUE_PAR_RANKING_PCT_BRL` e `LOW_VOLUME_DISTORTION_MAX_DELIVERED_BRL` para manter coerência de negócio.  
- **Mudar o que é “muitos críticos” ou a prioridade de lista de ataque** — ajustar `CRITICAL_*` (alertas secundários) e `FIRST_ACTION_CRITICAL_*` (primeira recomendação).  

Depois de mudanças, validar na tela com um recorte conhecido e rodar os testes (secção 9).

---

## 9. Testes

A inteligência e o dataset da página são cobertos principalmente por:

- `tests/test_bi_clientes_intel.py` — faixas do `decision_strip`, prioridade da primeira ação, domínio operacional, contextos, etc.  
- `tests/test_bi_clientes_dataset.py` — montagem do dataset, `decision_strip`, abas de ranking, payloads auxiliares.  
- `tests/test_bi_delivery_financial_consolidation.py` — encadeamento com dados financeiros e `executive_kpis` do dataset de clientes.  

**Após qualquer calibração dos limiares**, execute a suíte relevante (no mínimo os três arquivos acima) e corrija testes só se a **nova política** for intencional — caso contrário, ajuste as constantes até os testes refletirem o comportamento desejado.

```bash
python -m pytest tests/test_bi_clientes_intel.py tests/test_bi_clientes_dataset.py tests/test_bi_delivery_financial_consolidation.py -q
```
