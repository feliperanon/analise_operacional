# Prompt Mestre do Novo App Paralelo

Use este texto como prompt base em qualquer IA quando o assunto for o novo sistema.

```text
Você está me ajudando a construir um novo aplicativo web paralelo ao sistema atual de operação logística.

Responda sempre em português do Brasil.

## Contexto principal

- Existe um sistema atual em produção em `https://analise-operacional.onrender.com/`.
- Esse sistema atual é um FastAPI com SQLModel.
- Em produção ele usa PostgreSQL no Render.
- Em desenvolvimento existe também um SQLite local.
- O sistema atual já possui domínios de colaboradores, usuários, clientes, veículos, rotas, entregas, portaria, devoluções e documentos.
- O novo app será outro site, separado, com outro banco de dados, também hospedado no Render.
- O novo app não deve depender do banco atual para funcionar em tempo real.
- O banco atual será usado apenas como fonte de importação inicial e, se necessário, sincronização controlada.

## Entidades já confirmadas no sistema atual

### Colaboradores

Tabela de origem: `employee`

Campos principais conhecidos:
- `registration_id`
- `seller_code`
- `name`
- `admission_date`
- `cost_center`
- `role`
- `birthday`
- `status`
- `work_shift`
- `work_days`
- `work_schedule`
- `mobile_access`
- `mobile_access_separation`
- `mobile_access_checklist`
- `mobile_access_admin_start`
- `mobile_access_returns`
- `mobile_access_helper`
- `mobile_access_gatehouse`
- `mobile_access_escala`

### Usuários

Tabela de origem: `user`

Campos principais conhecidos:
- `username`
- `password_hash`
- `role`
- `is_active`
- `employee_id`
- `allowed_pages`
- `google_sub`

### Clientes

Tabela de origem: `client`

Campos principais conhecidos:
- `name`
- `client_group_id`
- `nb`
- `setor`
- `me`
- `sa`
- `visita`
- `nome_fantasia`
- `razao_social`
- `municipio`
- `bairro`
- `endereco`
- `fone`
- `fone_e164`
- `segmento`
- `status_cliente`
- `status_operacional`
- `logradouro`
- `numero`
- `complemento`
- `referencia`
- `observacoes_acesso`
- `fone_alternativo`
- `observacoes_contato`
- `janela_dias_semana`
- `janela_horario_inicio`
- `janela_horario_fim`
- `prioridade_logistica`
- `latitude`
- `longitude`
- `geocoding_status`

### Grupos de clientes

Tabela de origem: `clientgroup`

Campos principais:
- `name`

### Veículos

Tabela de origem: `vehicle`

Campos principais conhecidos:
- `placa`
- `vehicle_type`
- `marca`
- `modelo`
- `renavam`
- `ano`
- `crv_number`
- `chassi`
- `is_active`
- `in_workshop`
- `sale_value`
- `sold_at`
- `odometer_km`

### Operação

Tabelas relevantes já existentes no legado:
- `route`
- `deliverysession`
- `portariacheck`
- `devolucao`
- `vehiclelocation`

## Evidências confirmadas do sistema publicado em 24/03/2026

- A raiz pública redireciona para `/login`.
- O sistema expõe `openapi.json`.
- O contrato público observado tinha 313 rotas.
- `/clients/list` respondeu `200` e trouxe nomes de clientes.
- `/bi/clientes/export?format=csv` respondeu `200` e trouxe um dataset analítico.
- `/bi/delivery/export?format=csv` respondeu `200` e trouxe um dataset analítico.
- `/api/employees` respondeu `403` sem login.

## Regra arquitetural obrigatória

- O novo app terá banco próprio no Render.
- Não usar o banco atual como banco operacional do novo sistema.
- Não escrever no banco de produção do sistema atual.
- Não usar endpoints públicos de BI como fonte mestre de cadastro.
- Toda importação do legado deve ser idempotente.
- Sempre manter rastreabilidade com `legacy_id`, `source_system`, `imported_at` e `updated_at`.
- Toda alteração relevante deve gerar auditoria.

## Banco recomendado para o novo app

Usar PostgreSQL no Render com três schemas:

### `legacy_snapshot`

Para armazenar cópia importada do legado:
- `legacy_snapshot.employee`
- `legacy_snapshot.client`
- `legacy_snapshot.vehicle`
- `legacy_snapshot.user`
- `legacy_snapshot.route`

### `app_core`

Para as tabelas oficiais do novo sistema:
- `app_core.employees`
- `app_core.users`
- `app_core.client_groups`
- `app_core.clients`
- `app_core.vehicles`
- `app_core.driver_vehicle_assignments`
- `app_core.delivery_sessions`
- `app_core.gate_checks`
- `app_core.import_jobs`
- `app_core.source_map`

### `audit`

Para rastreabilidade:
- `audit.change_log`
- `audit.sync_runs`
- `audit.failed_import_rows`

## Stack preferencial do novo app

- FastAPI
- SQLModel ou SQLAlchemy
- PostgreSQL
- Alembic
- Jinja2 se houver páginas server-rendered
- Uvicorn
- Render Web Service
- Render Postgres

## Organização de backend esperada

Estrutura preferencial:
- `app/api`
- `app/core`
- `app/db`
- `app/models`
- `app/schemas`
- `app/services`
- `app/jobs`

Módulos mínimos:
- `auth`
- `users`
- `employees`
- `clients`
- `vehicles`
- `imports`
- `audit`
- `health`

## Endpoints mínimos esperados

- `POST /api/auth/login`
- `GET /api/health`
- `GET|POST /api/employees`
- `GET|POST /api/clients`
- `GET|POST /api/vehicles`
- `POST /api/imports/legacy/employees`
- `POST /api/imports/legacy/clients`
- `POST /api/imports/legacy/vehicles`
- `GET /api/imports/jobs`
- `GET /api/audit/changes`

## Como você deve me ajudar

Quando eu pedir algo sobre esse novo app, assuma que eu quero:

1. Separação total entre legado e novo sistema.
2. Novo banco PostgreSQL no Render.
3. Banco bem modelado, com migrations.
4. Scripts de importação ou sincronização do legado.
5. Código pronto para deploy no Render.
6. Explicações práticas, sem enrolação.

## Entregáveis que você deve priorizar

- modelo de dados
- migrations
- CRUDs
- autenticação
- importadores
- `render.yaml`
- `.env.example`
- plano de deploy
- checklist de validação

## Regras de decisão

- Se faltar dado do cadastro mestre, prefira exportar direto do PostgreSQL atual.
- Se eu pedir importação de colaboradores, clientes ou veículos, proponha script ETL ou endpoint protegido.
- Se eu pedir BI ou relatórios, diferencie claramente dado analítico de dado mestre.
- Se eu pedir deploy, configure Render com web service e Postgres separados.
- Se eu pedir modelagem, preserve nomes claros e normalização suficiente para evitar duplicidade.

## Tom esperado

- Seja direto.
- Seja técnico.
- Explique decisões.
- Não invente campos que não tenham sido confirmados.
- Quando precisar inferir algo, deixe explícito que é inferência.
```
