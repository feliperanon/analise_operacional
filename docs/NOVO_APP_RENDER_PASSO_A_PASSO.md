# Novo App Paralelo no Render

Data de referência: 24/03/2026.

## 1. Contexto confirmado

- Sistema atual em produção: `https://analise-operacional.onrender.com/`
- A raiz pública redireciona para `/login`.
- A aplicação publicada expõe `openapi.json` e, na verificação de 24/03/2026, o contrato tinha 313 rotas.
- O repositório atual usa `FastAPI + SQLModel + PostgreSQL em produção + SQLite local`.
- O deploy atual já está preparado para Render com `render.yaml`, `Procfile` e `RENDER.md`.

## 2. O que já existe hoje e pode servir de base

### Cadastros já modelados no código atual

- `employee`: colaboradores, matrícula, função, turno, centro de custo, agenda, permissões mobile.
- `user`: login, senha, papel, vínculo com colaborador e páginas permitidas.
- `client` e `clientgroup`: clientes, grupo/rede, endereço, telefones, prioridade, status operacional, geolocalização.
- `vehicle`: caminhões/veículos, placa, marca, modelo, RENAVAM, chassi, hodômetro, oficina, venda.
- `route`: rota/entrega/separação.
- `deliverysession`: sessão diária de saída/retorno do motorista.
- `portariacheck`: conferência de saída/chegada na portaria.
- `devolucao`: devoluções.
- `docinstitucional`: documentos institucionais.

### Evidências observadas no sistema publicado

- `/clients/list` respondeu `200` e retornou uma lista pública com 16.740 nomes de clientes na verificação de 24/03/2026.
- `/bi/clientes/export?format=csv` respondeu `200` e gerou um CSV analítico com 1.763 linhas.
- `/bi/delivery/export?format=csv` respondeu `200` e gerou um CSV analítico com 3.222 linhas.
- `/api/employees` respondeu `403` sem autenticação.

### Observação importante

- O `database.db` local é apenas um snapshot de desenvolvimento.
- No arquivo local havia `154` colaboradores, `16.687` clientes e `38` veículos.
- Tabelas mais novas como `portariacheck` e `docinstitucional` ainda não existiam nesse SQLite local, então ele não representa 100% da produção.

## 3. Decisão de arquitetura recomendada

- Criar um novo app em paralelo.
- Criar um novo banco PostgreSQL só para esse novo app.
- Não usar o banco atual como banco transacional do novo site.
- Usar o sistema atual apenas como fonte de importação inicial e, se necessário, sincronização controlada.
- Manter os dois sistemas independentes para evitar quebra no ambiente atual.

## 4. Qual banco usar no novo app

Recomendação: um único PostgreSQL no Render, mas organizado em schemas separados.

### Schema `legacy_snapshot`

Uso: guardar uma cópia importada do sistema atual.

Tabelas mínimas:

- `legacy_snapshot.employee`
- `legacy_snapshot.client`
- `legacy_snapshot.vehicle`
- `legacy_snapshot.user`
- `legacy_snapshot.route`

### Schema `app_core`

Uso: tabelas oficiais do novo sistema.

Tabelas recomendadas:

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

### Schema `audit`

Uso: auditoria e rastreabilidade.

Tabelas recomendadas:

- `audit.change_log`
- `audit.sync_runs`
- `audit.failed_import_rows`

## 5. O que copiar do banco atual e o que criar novo

### Copiar do sistema atual

- Colaboradores.
- Usuários.
- Clientes.
- Grupos de clientes.
- Caminhões/veículos.
- Rotas antigas, se o novo app precisar histórico.
- Sessões de entrega e portaria, se o novo app precisar operação completa.

### Criar do zero no novo sistema

- `source_map` para mapear `legacy_id -> new_id`.
- `import_jobs` para controlar importação por lote.
- `sync_runs` para histórico de sincronizações.
- `change_log` para auditoria do novo app.
- `driver_vehicle_assignments` para vínculo histórico motorista x veículo.
- Qualquer regra nova do novo negócio, sem contaminar o legado.

## 6. Como buscar os dados do sistema atual

### Melhor opção para cadastros completos

- Acessar diretamente o PostgreSQL atual do Render usando a `External Database URL` para exportação.
- Isso é o melhor caminho para colaboradores, usuários, clientes completos e veículos.

### Segunda melhor opção

- Criar endpoints protegidos temporários no sistema atual apenas para exportação autenticada.

### O que não usar como fonte mestre

- `/clients/list` porque traz basicamente nomes.
- `/bi/clientes/export` porque é um dataset analítico, não um cadastro mestre.
- `/bi/delivery/export` porque é analítico e agregado para BI.

## 7. Backend recomendado para o novo app

- `FastAPI`
- `SQLAlchemy/SQLModel`
- `Alembic` para migrations
- `Pydantic Settings` para configuração
- `PostgreSQL`
- `Uvicorn` no início
- `Gunicorn + UvicornWorker` se precisar escalar depois

### Módulos de backend mínimos

- `auth`
- `users`
- `employees`
- `clients`
- `vehicles`
- `imports`
- `audit`
- `health`

### Endpoints mínimos

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

## 8. Estrutura sugerida do projeto

```text
novo_app/
  app/
    api/
    core/
    db/
    models/
    schemas/
    services/
    jobs/
    templates/
    static/
    main.py
  alembic/
  tests/
  .env.example
  requirements.txt
  render.yaml
  README.md
```

## 9. Passo a passo completo

### Fase 1. Criar o repositório do novo app

1. Crie um novo repositório para não misturar com o sistema atual.
2. Defina o nome do app, por exemplo `operacao-paralela`.
3. Suba a estrutura base com `FastAPI`.

### Fase 2. Preparar o backend local

1. Crie um ambiente virtual.
2. Instale dependências.
3. Configure `.env.example`.
4. Defina `DATABASE_URL` apontando para Postgres.
5. Crie `alembic` desde o início.

Exemplo de dependências:

```txt
fastapi
uvicorn
sqlmodel
sqlalchemy
alembic
psycopg2-binary
python-dotenv
jinja2
python-multipart
passlib[bcrypt]
python-jose[cryptography]
```

### Fase 3. Modelar o banco novo

1. Crie primeiro `employees`, `users`, `clients`, `client_groups` e `vehicles`.
2. Depois crie `import_jobs`, `source_map` e `change_log`.
3. Só depois avance para sessões, portaria e histórico.

### Fase 4. Criar migrations

1. Gere a migration inicial.
2. Gere migrations separadas por domínio.
3. Nunca dependa só de `create_all()` em produção.

### Fase 5. Criar CRUDs principais

1. Cadastro de colaboradores.
2. Cadastro de clientes.
3. Cadastro de caminhões/veículos.
4. Login e permissões.
5. Busca e filtros.

### Fase 6. Criar importadores do legado

1. Importador de colaboradores.
2. Importador de clientes.
3. Importador de veículos.
4. Importador de usuários.
5. Importador opcional de rotas/histórico.

Regras obrigatórias do importador:

- idempotência
- log de erros por linha
- `legacy_id`
- `source_system`
- `imported_at`
- `updated_at`

### Fase 7. Criar `render.yaml`

Exemplo inicial:

```yaml
services:
  - type: web
    name: operacao-paralela
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: operacao-paralela-db
          property: connectionString
      - key: SECRET_KEY
        generateValue: true
      - key: PYTHON_VERSION
        value: 3.11.11
      - key: APP_BASE_URL
        sync: false
      - key: ADMIN_EMAIL
        sync: false
      - key: ADMIN_PASS
        sync: false

databases:
  - name: operacao-paralela-db
    plan: starter
```

Observação:

- Ajuste `plan` para o plano realmente disponível no seu workspace do Render.
- Para protótipo, você pode usar o menor plano disponível.
- Para produção, evite depender de plano gratuito quando houver limitação de disponibilidade.

### Fase 8. Criar recursos no Render

1. Suba o repositório para GitHub.
2. No Render, crie um `Blueprint` ou um `Web Service`.
3. Crie também um `Render Postgres`.
4. Garanta que web service e banco fiquem na mesma região.
5. Use a `Internal Database URL` para a aplicação dentro do Render.

### Fase 9. Configurar variáveis de ambiente

Variáveis mínimas:

- `DATABASE_URL`
- `SECRET_KEY`
- `ADMIN_EMAIL`
- `ADMIN_PASS`
- `APP_BASE_URL`
- `PYTHON_VERSION`

Variáveis úteis para integração com o legado:

- `LEGACY_BASE_URL`
- `LEGACY_DATABASE_URL`
- `LEGACY_ADMIN_EMAIL`
- `LEGACY_ADMIN_PASS`

### Fase 10. Deploy

1. Faça o primeiro deploy.
2. Rode migrations.
3. Crie o usuário admin inicial.
4. Teste `/api/health`.
5. Teste login.
6. Teste cadastros.

### Fase 11. Carga inicial de dados

1. Exporte colaboradores do sistema atual.
2. Exporte clientes completos do sistema atual.
3. Exporte veículos do sistema atual.
4. Importe para `legacy_snapshot`.
5. Normalize e grave em `app_core`.
6. Grave o mapeamento em `source_map`.

### Fase 12. Validação

Checklist:

- contagem de colaboradores bate
- contagem de clientes bate
- contagem de veículos bate
- usuários ativos batem
- filtros funcionam
- logs de auditoria funcionam
- importação repetida não duplica dados

## 10. Regras para não errar

- Não escreva no banco de produção do sistema atual.
- Não use endpoints de BI como origem mestre de cadastro.
- Não misture SQLite local com banco oficial do novo app.
- Não faça o novo app depender online do banco antigo para funcionar.
- Sempre tenha `legacy_id` e `source_system`.
- Toda importação deve ser repetível sem duplicar registros.

## 11. Melhor caminho prático

Se você quer fazer certo sem retrabalho, siga esta ordem:

1. Novo repositório.
2. Novo Postgres no Render.
3. CRUD de `employees`, `clients` e `vehicles`.
4. Script de importação a partir do banco atual.
5. Deploy.
6. Validação.
7. Só depois adicionar regras novas e módulos extras.

## 12. Resumo objetivo

- Sim, dá para fazer no Render sem problema.
- O certo é criar outro `Web Service` e outro `PostgreSQL`.
- O sistema atual deve ser só fonte de importação, não a base operacional do novo app.
- Para `colaboradores`, `clientes` e `caminhões`, o ideal é exportar direto do banco atual.
- Para qualquer evolução futura, use migrations e banco separado desde o primeiro dia.
