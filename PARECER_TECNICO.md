# 🛡️ PARECER TÉCNICO SISTÊMICO — ANTIGRAVITY

**Data:** 08/01/2026
**Status do Sistema:** 🟡 **ESTÁVEL COM RISCOS LATENTES**
**Arquitetura:** Híbrida (Monólito Modular com Frontend Decoplado)

Após análise profunda dos arquivos `main.py`, `models.py`, templates e lógica de frontend, apresento o parecer completo sobre a saúde e robustez do sistema **Smart Flow / Análise Operacional**.

---

## 1. 🏛️ Decisões Arquiteturais & Conformidade

O sistema evoluiu bem para uma arquitetura **API-First**, mas carrega heranças que violam o princípio da "Fonte Única de Verdade".

| Pilar | Status | Análise |
| :--- | :---: | :--- |
| **API-First** | ✅ | O frontend (`smart_flow.html` + `main.js`) consome dados via JSON. O template HTML é estrutural, o que é excelente. |
| **Anti-500** | ✅ | Existe Middleware de Exception Global com `trace_id`. Erros são logados e não "explodem" na cara do usuário (retornam JSON ou HTML amigável). |
| **Cache** | ❌ | **CRÍTICO.** Não encontrei headers explícitos de `Cache-Control: no-store` nas rotas da API ou HTML. Isso é a causa raiz de "funciona pra mim, não pra você". |
| **Dados (Sync)** | ⚠️ | **ALTO RISCO.** Existe duplicidade de escrita. O endpoint `/save` grava em `EmployeeAllocation` (tabela nova) E em `DailyOperation.attendance_log` (tabela legada). Se uma falhar, o relatório (que lê do legado) diverge do dashboard (que lê do novo). |
| **Relatórios** | ⚠️ | O relatório PDF (`routine_report`) recria a lógica de cálculo de KPIs que já existe no Frontend. Lógica duplicada = números divergentes. |

---

## 2. 💀 Pré-Mortem: Riscos Previstos

Se não agirmos, estes são os problemas que acontecerão nas próximas 2-4 semanas:

1.  **Divergência Dashboard vs Relatório:** O usuário vai reclamar que "Na tela tem 45 presentes, mas no PDF saiu 44".
    *   *Causa:* O Relatório lê `DailyOperation`, enquanto o Dashboard lê `EmployeeAllocation`.
2.  **O "Bug do Cache":** Após um deploy, usuários verão versões antigas do JS (`main.js`) quebrando a chamada de API.
3.  **Perda de Dados de Produção:** A tonelagem está sendo salva no objeto `DailyOperation`, mas se o usuário editar no Dashboard antigo e salvar, pode sobrescrever o cálculo automático das rotas.

---

## 3. 🛠️ Implementação Sugerida (Plano de Blindagem)

Para elevar o sistema ao nível **Antigravity** (Imune a erros recorrentes), recomendo as seguintes ações imediatas:

### A. Blindagem de Cache (Backend)
Adicionar middleware que força headers anti-cache em todas as respostas dinâmicas.

```python
# Em main.py (Adicionar logo após criar o 'app')
@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path.startswith("/smart-flow"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response
```

### B. Unificar Fonte de Verdade (Relatório)
O relatório (`routine_report`) deve parar de ler o campo JSON `attendance_log`. Ele deve consultar as tabelas reais (`EmployeeAllocation` e `EmployeeRoutine`), garantindo que **o que está no banco novo é o que sai no papel**.

### C. Transação Atômica no Save
O endpoint `save_allocations` já está robusto, mas deve garantir que o cálculo da tonelagem (vindo das rotas) sempre prevaleça sobre dados manuais antigos.

---

## 4. ✅ Checklist de Validação (Quality Assurance)

Antes de considerar qualquer nova feature, verifique:

*   [ ] **Cache:** O Header `Cache-Control: no-store` aparece no DevTools > Network ao carregar o Smart Flow?
*   [ ] **Relatório:** Os números do PDF batem EXATAMENTE com os números da tela do Smart Flow? (Isso valida a fonte única).
*   [ ] **Erro 500:** Se eu desligar o banco intencionalmente, o frontend mostra um alerta amigável ou fica em tela branca? (Atualmente `api.js` retorna objeto vazio, o que é "seguro" mas pode enganar o usuário achando que está tudo zero).
*   [ ] **Timezone:** Os logs de erro (`logs.txt`) estão com o horário correto de Brasília?

---

## 5. Conclusão

Seu sistema está **70% do caminho para a excelência**. A base é sólida (Python/FastAPI + JS Vanilla Modular). O perigo mora na **persistência dúbia (Legado vs Novo)** e na **falta de controle de cache**.

**Recomendação Imediata:**
1.  Aplicar o Middleware de Cache.
2.  Refatorar o Relatório para ler das tabelas novas (`EmployeeAllocation`), matando a dependência do JSON legado para leitura.
