# Módulo do Líder – Visão e Roadmap

## Opinião geral

Faz muito sentido centralizar no **Smart Flow** (ou num hub “Módulo Líder”) tudo que o líder precisa para o dia a dia: check-in, falta/atestado, onde está, checklists em atraso, uso do app de rota e velocidade da equipe, além de **enviar tarefas**. Isso reduz troca de tela e dá uma visão única de “quem está ok” e “quem precisa de ação”.

Sugestão: tratar o **Smart Flow** como a **página principal do líder** e ir acrescentando abas ou subpáginas (ou cards de resumo) para cada bloco abaixo. Assim o módulo cresce de forma organizada.

---

## O que já existe hoje

| Necessidade | Situação atual |
|------------|----------------|
| **Check-in de colaboradores** | ✅ `DailyOperation.attendance_log` + tela Smart Flow (presente, falta, atestado, férias, afastamento). Líder altera status por colaborador. |
| **Onde está (alocação)** | ✅ Alocação por setor/subsector no Smart Flow (drag-and-drop). |
| **Falta / atestado** | ✅ Status no `attendance_log`; eventos `Event` (tipo falta/atestado); import de atestados; alertas de ausência. |
| **Checklist paleteiras** | ✅ `TranspalletChecklist` + painel admin `/admin/routine/checklists`. Falta **visão para o líder**: “quem não fez hoje”. |
| **Checklist empilhadeiras** | ⚠️ Hoje só existe checklist de **transpaleteira** no modelo. Empilhadeira pode ser: (a) novo tipo de checklist no mesmo fluxo, ou (b) novo modelo `ForkliftChecklist` – definir no desenho. |
| **Rotas (app)** | ✅ `Route` por colaborador/data/turno; página Separação. Falta **visão líder**: “quem deveria estar no app e não está” + **velocidade da equipe**. |
| **Enviar tarefas** | ❌ Não existe. Será funcionalidade nova (modelo + tela + notificação ou lista no app). |

---

## Proposta de estrutura do Módulo Líder

Base: **uma entrada** para o líder (ex.: `/smart-flow` ou `/lider`) e de lá acessar:

1. **Smart Flow (atual)** – Check-in + alocação + KPIs do turno.
2. **Checklists em dia** – Quem **não** fez checklist (paleteira e, no futuro, empilhadeira).
3. **Rotas e app** – Quem **não** está usando o app para rota + **velocidade da equipe** (ex.: kg/h, rotas concluídas).
4. **Tarefas** – Enviar tarefas para colaboradores (nova página + backend).

### Opção A – Tudo sob `/smart-flow`
- `/smart-flow` → mesma tela atual, com **cards/links** no topo ou em abas:
  - “Checklists em atraso” → abre lista ou modal.
  - “Rotas / uso do app” → abre lista + métricas de velocidade.
  - “Tarefas” → link para `/smart-flow/tarefas` (ou `/lider/tarefas`).
- Vantagem: um só lugar. Desvantagem: página pode ficar pesada; dá para ir para subpáginas conforme crescer.

### Opção B – Hub “Líder” com subpáginas
- `/lider` (ou manter `/smart-flow` como hub):
  - `/smart-flow` – Check-in + alocação (como hoje).
  - `/lider/checklists` – Quem não fez checklist (empilhadeira + paleteira).
  - `/lider/rotas` – Uso do app + velocidade da equipe.
  - `/lider/tarefas` – Enviar e listar tarefas.
- Vantagem: URLs claras e responsabilidades separadas. Permissão: só `leader` (e admin) acessam `/lider/*` e `/smart-flow`.

Recomendação: **Opção B**, com menu “Líder” no base (e no mobile) agrupando Smart Flow, Checklists, Rotas e Tarefas.

---

## Roadmap sugerido (para implementar depois)

### Fase 1 – Check-in e visão do que falta (já quase pronto)
- Revisar se na tela do Smart Flow está **óbvio** para o líder: falta, atestado, onde está (setor).
- Se quiser, um **resumo no topo**: “X presentes, Y atestado, Z falta” e link para quem está sem atestado quando for obrigatório.

### Fase 2 – Tela “Checklists em dia”
- **Objetivo:** listar quem **não** fez checklist no dia/turno.
- **Paleteira:** usar `TranspalletChecklist` (data + shift). Lista: colaboradores que deveriam fazer (ex.: quem tem `mobile_access_checklist`) e **não** têm registro naquele dia/turno.
- **Empilhadeira:** definir se é outro tipo de checklist (novo modelo ou mesmo fluxo com `equipment_type`) e então aplicar a mesma lógica “quem deveria e não fez”.
- **Rota sugerida:** `/lider/checklists` ou `/smart-flow/checklists`. Filtro: data, turno, tipo (paleteira / empilhadeira).

### Fase 3 – Tela “Rotas e uso do app”
- **Quem não está no app fazendo rota:**
  - Definir “quem deveria”: ex. colaboradores com `mobile_access_separation` no turno do dia.
  - Comparar com quem tem `Route` (ou atividade de rota) naquele dia/turno → listar quem não tem.
- **Velocidade da equipe:**
  - Já existe `Route` com tonnage e horários → dá para calcular kg/h por pessoa e médias do turno/equipe (cards ou tabela).
- **Rota sugerida:** `/lider/rotas` ou `/smart-flow/rotas`. Filtro: data, turno.

### Fase 4 – Página “Enviar tarefas”
- **Backend:** novo modelo, ex.: `LeaderTask` (título, descrição, prioridade, destinatários – lista de `employee_id` ou “todos do setor”, data limite, status, criado_por, criado_em).
- **Tela líder:** formulário para criar tarefa + listar tarefas enviadas (e status: pendente, vista, concluída).
- **Colaborador:** ver tarefas no app (mobile) ou em página “Minhas tarefas” (notificação ou badge).
- **Rota sugerida:** `/lider/tarefas` (lista + criar). No mobile: “Tarefas” no menu.

---

## Resumo

- **Ideia:** Muito boa; centralizar no módulo do líder check-in, falta/atestado, onde está, checklists em atraso, uso do app de rota, velocidade da equipe e envio de tarefas.
- **Hoje:** Check-in e alocação já estão no Smart Flow; falta visão para o líder sobre “quem não fez checklist” e “quem não está no app de rota” + velocidade; tarefas é feature nova.
- **Próximos passos:** (1) Definir se checklist empilhadeira é novo tipo ou novo modelo. (2) Criar rotas `/lider/checklists` e `/lider/rotas` (ou sob `/smart-flow`). (3) Implementar modelo e tela de tarefas. (4) Revisar permissões (só líder/admin acessam essas rotas).

Quando for implementar, dá para seguir este doc como checklist e ir riscando cada item.

---

## Implementado (jan/2025)

- **Menu Líder** (base e mobile): Smart Flow, Checklists em dia, Rotas e velocidade, Tarefas.
- **Fase 2 – Checklists em dia:** `/lider/checklists` – lista quem não fez checklist de paleteira no dia/turno (filtro data e turno).
- **Fase 3 – Rotas e uso do app:** `/lider/rotas` – lista quem deveria estar no app e não tem rota no dia/turno; tabela de velocidade (kg/h por colaborador).
- **Fase 4 – Tarefas:** modelo `LeaderTask` e `LeaderTaskResponse`; `/lider/tarefas` (criar e listar); API `POST /api/lider/tarefas`, `GET /api/lider/minhas-tarefas`, `POST .../marcar-visto`, `POST .../concluir`; página mobile `/mobile/tarefas` (Minhas Tarefas) para o colaborador ver e marcar visto/concluir.
- Permissões: quem tem acesso ao Smart Flow (`smart_flow` em allowed_pages ou admin) acessa `/lider/*`.
