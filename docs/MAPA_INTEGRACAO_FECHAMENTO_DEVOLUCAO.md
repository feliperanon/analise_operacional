# MAPA DE INTEGRAÇÃO — Fechamento Automático e Devolução como Exceção

## FASE 0 — ARQUIVOS RELEVANTES

### Models / Tabelas
| Arquivo | Responsabilidade | Alterações |
|---------|------------------|------------|
| `models.py` | Route, Devolucao, DevolucaoMotivo, DevolucaoResponsabilidade | Devolucao: adicionar `route_id` (opcional FK) para vincular devolução à parada |
| `database.py` | Sessão, engine | — |

### Rotas / Endpoints
| Arquivo | Endpoint | Alterações |
|---------|----------|------------|
| `main.py` | POST `/separacao/delivery/status` | Manter (iniciar/finalizar/devolucao por parada) |
| `main.py` | POST `/api/mobile/delivery/route/{id}/action` | Manter (mobile) |
| `main.py` | POST `/separacao/delivery/reopen` | Manter |
| `main.py` | POST `/separacao/delivery/finish-route` | **NOVO** — finalizar rota inteira (regra de ouro) |
| `main.py` | GET `/api/mobile/returns/data?days=` | Já existe — usado pelo card Devoluções |

### Templates
| Arquivo | Responsabilidade | Alterações |
|---------|------------------|------------|
| `templates/routes.html` | Lista de rotas, grupos por motorista, botões | Adicionar botão "Finalizar rota" por grupo + modal de confirmação |
| `templates/mobile/delivery.html` | Mobile entregas | — |
| `templates/mobile/dashboard.html` | Dashboard mobile (card Devoluções) | Já usa API; garantir filtros days |
| `templates/devolucoes.html` | Gestão de devoluções | — |
| `templates/bi_delivery.html` | BI entregas e devoluções | — |

### BI / Services
| Arquivo | Responsabilidade | Alterações |
|---------|------------------|------------|
| `bi_delivery_routes.py` | BI Delivery | Queries já usam Route.delivery_status; números batem após fechamento |
| `devolucoes_routes.py` | APIs e páginas de devoluções | — |
| `devolucoes_service.py` | Regras de validação/import | — |

---

## MODELO DE DADOS

### Route (existente)
- 1 registro = 1 parada
- `delivery_status`: pendente | iniciada | entregue | devolucao | reaberta | cancelada
- `valor_devolucao`, `devolucao_volume`, `delivery_return_reason`, `delivery_return_category` — preenchidos quando devolução é marcada

### Devolucao (existente + novo campo)
- **route_id** (opcional, FK Route): vincular devolução manual/import à parada específica
- Usado para: (a) fechamento automático considerar devoluções lançadas em /devolucoes; (b) drill-through no BI

### Migração
- `ensure_devolucao_route_id()` — adiciona coluna `route_id` em `devolucao` se não existir

---

## FLUXOS E REGRAS

### Regra de ouro (OBRIGATÓRIA)
1. Se existir devolução registrada para a parada → status final: **devolucao**
2. Se NÃO existir devolução → status final: **entregue** ao finalizar rota

### "Devolução registrada" = uma das opções
- **Opção A**: `Route.delivery_status == "devolucao"` (já marcado via modal/mobile)
- **Opção B**: `exists Devolucao where route_id = Route.id` (quando route_id estiver preenchido)

### Fechamento automático (endpoint novo)
- **POST /separacao/delivery/finish-route** (date, shift, employee_id)
- Para cada Route da rota (date, shift, employee_id, type=delivery):
  - Se `delivery_status in (entregue, devolucao)` → ignorar (idempotente)
  - Se `delivery_status in (pendente, iniciada, reaberta)` → se tem devolução → devolucao, senão → entregue
- Transação única
- Resumo: total_stops, delivered_count, returned_count, return_value_total, return_rate_percent

### Registrar devolução (existente)
- Modal: POST `/separacao/delivery/status` action=devolucao → atualiza Route
- Mobile: POST `/api/mobile/delivery/route/{id}/action` action=devolucao → atualiza Route
- /devolucoes: POST `/api/devolucoes` → cria Devolucao (sem route_id por padrão; futuro: permitir route_id)

---

## CHECKLIST DE VALIDAÇÃO (5 min)
1. Acessar /separacao, selecionar data e turno
2. Em um grupo com paradas pendentes, clicar "Finalizar rota"
3. Confirmar no modal e submeter
4. Verificar: paradas sem devolução → entregue; paradas com devolução → devolucao
5. Rodar novamente (idempotência): não alterar paradas já fechadas

---

## ENTREGA REALIZADA

### 1. Arquivos alterados
- `models.py`: Devolucao.route_id (opcional FK)
- `main.py`: ensure_devolucao_route_id(), POST /separacao/delivery/finish-route
- `templates/routes.html`: botão "Finalizar rota" por grupo
- `docs/MAPA_INTEGRACAO_FECHAMENTO_DEVOLUCAO.md`: documento
- `tests/test_finish_route.py`: testes unitários

### 2. Endpoints
- **POST /separacao/delivery/finish-route** (Form: date, shift, employee_id)
  - Finaliza rota inteira (regra de ouro)
  - Idempotente

### 3. Como rodar testes
```bash
python -m pytest tests/test_finish_route.py -v
```
