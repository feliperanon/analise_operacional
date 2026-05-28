# Banco de dados no Google (Cloud SQL) — guia do zero

Este projeto usa **PostgreSQL**. No Google, o serviço equivalente ao Postgres do Render é o **Cloud SQL for PostgreSQL**.

Você **não precisa** continuar no Render para o banco. O app continua rodando no seu PC (ou depois no Cloud Run); só troca **onde** ficam os dados.

---

## O que você vai criar (resumo)

1. Conta Google + projeto no Cloud Console  
2. Instância **Cloud SQL → PostgreSQL**  
3. Banco + usuário + senha  
4. Colar a conexão no `.env`  
5. (Opcional) Copiar dados do Render para o Google  

---

## Parte 1 — Criar o banco no Google (15–30 min)

### 1. Entrar no console

1. Abra https://console.cloud.google.com/  
2. Faça login com Gmail.  
3. **Selecionar projeto** → **Novo projeto** → nome: `analise-operacional` → **Criar**.

### 2. Ativar faturamento

Cloud SQL exige **conta de faturamento** (há camada gratuita limitada; depois cobra por uso).

Menu ☰ → **Faturamento** → vincule um cartão ao projeto (se ainda não tiver).

### 3. Criar instância PostgreSQL

1. Menu ☰ → **SQL** → **Criar instância** → escolha **PostgreSQL**.  
2. **ID da instância**: `analise-db` (exemplo).  
3. **Senha do usuário postgres**: gere uma senha forte e **anote**.  
4. Região: `southamerica-east1` (São Paulo) se disponível.  
5. Plano: comece com a opção **mais barata / desenvolvimento** (pode ajustar depois).  
6. **Criar** e aguarde ficar com status **Em execução** (ícone verde).

### 4. Criar o banco da aplicação

1. Abra a instância → aba **Bancos de dados** → **Criar banco de dados**.  
2. Nome: `analise` (ou outro; use o mesmo no `.env`).

### 5. Permitir conexão do seu PC (IP público — jeito mais simples)

1. Na instância → **Conexões** → **Redes**.  
2. **Adicionar rede** → marque **IP público**.  
3. Em **Redes autorizadas**, adicione o IP da sua internet (o Google mostra “Meu IP” em alguns fluxos) ou `0.0.0.0/0` **só para teste** (menos seguro).  
4. Anote o **IP público** da instância (na visão geral).

### 6. Montar a URL no `.env`

No arquivo `.env` do projeto:

```env
# Troque pelos seus valores reais:
DATABASE_URL=postgresql://postgres:SUA_SENHA@IP_PUBLICO:5432/analise?sslmode=require

# Recomendado ao usar Google em produção:
REQUIRE_GCP_DB=true
GCP=true

# Não use SQLite se quer o Google:
# FORCE_LOCAL_DB=false
```

Remova ou comente `RENDER=true` e URLs antigas do Render se não for mais usar.

Reinicie o servidor e teste:

```powershell
cd c:\Projeto\Analise
.\.venv\Scripts\python.exe scripts\gcp_db_check.py
```

Se aparecer `OK — origem: gcp`, o banco Google está funcionando.

---

## Parte 2 — Pacotes instalados no projeto

Já estão no `requirements.txt`:

| Pacote | Uso |
|--------|-----|
| `psycopg2-binary` | Driver PostgreSQL (já existia) |
| `cloud-sql-python-connector[psycopg2]` | Conexão segura ao Cloud SQL sem IP público |
| `google-genai` | IA Gemini (opcional) |

Instalar no ambiente virtual:

```powershell
cd c:\Projeto\Analise
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## Parte 3 — Modo Connector (sem IP público)

Use se **não** quiser liberar IP público na instância.

No `.env`:

```env
USE_CLOUD_SQL_CONNECTOR=true
CLOUD_SQL_CONNECTION_NAME=seu-projeto:southamerica-east1:analise-db
CLOUD_SQL_USER=postgres
CLOUD_SQL_PASSWORD=sua_senha
CLOUD_SQL_DB=analise
REQUIRE_GCP_DB=true
```

No PC, uma vez:

```powershell
# Instalar Google Cloud CLI: https://cloud.google.com/sdk/docs/install
gcloud auth application-default login
gcloud config set project SEU_PROJETO_ID
```

Conta de serviço (servidor/CI): baixe JSON no Console → **IAM → Contas de serviço** com papel **Cloud SQL Client** e defina:

```env
GOOGLE_APPLICATION_CREDENTIALS=C:\caminho\chave.json
```

---

## Parte 4 — Copiar dados do Render para o Google

Com o Postgres do Google já acessível:

```powershell
$env:SOURCE_DATABASE_URL="postgresql://...url_do_render..."
$env:TARGET_DATABASE_URL="postgresql://...url_do_google..."
.\.venv\Scripts\python.exe scripts\copy_postgres_data.py
```

Ou use os parâmetros `--source-url` e `--target-url`.

---

## Parte 5 — Subir o app (onde roda o código)

| Onde | Banco |
|------|--------|
| **Seu PC** (`uvicorn`) | `DATABASE_URL` com IP público ou Connector + `gcloud auth` |
| **Cloud Run** (futuro) | Socket `/cloudsql/...` ou Connector; variável `GCP=true` |

O Render **não é obrigatório**. Você pode manter o app só no PC apontando para o Cloud SQL.

---

## Variáveis de ambiente (referência)

| Variável | Descrição |
|----------|-----------|
| `DATABASE_URL` | URL PostgreSQL (Google, Render, etc.) |
| `GOOGLE_DATABASE_URL` | Alias opcional da mesma URL |
| `CLOUD_SQL_CONNECTION_NAME` | `projeto:região:instância` |
| `CLOUD_SQL_USER` / `CLOUD_SQL_PASSWORD` / `CLOUD_SQL_DB` | Credenciais para socket ou connector |
| `USE_CLOUD_SQL_CONNECTOR` | `true` = usa biblioteca Google em vez de IP |
| `REQUIRE_GCP_DB` | `true` = não cai em SQLite se o Postgres falhar |
| `GCP` | `true` = perfil produção / pool maior |
| `FORCE_LOCAL_DB` | `true` = ignora nuvem e usa `database.db` local |

---

## Problemas comuns

| Erro | Solução |
|------|---------|
| Timeout / connection refused | IP autorizado no Cloud SQL? Senha correta? |
| SSL required | Mantenha `?sslmode=require` na URL ou `DB_SSLMODE=require` |
| Connector failed | `pip install cloud-sql-python-connector[psycopg2]` + `gcloud auth application-default login` |
| App usa SQLite | Remova `FORCE_LOCAL_DB=true` e configure `DATABASE_URL` |

---

## Próximo passo

Depois que `scripts/gcp_db_check.py` passar, suba o app normalmente (`uvicorn`). As tabelas são criadas na primeira execução (`create_db_and_tables`).

Se quiser, no chat peça: **“ajuda a colar minha URL do Cloud SQL no .env”** (sem enviar senha em texto aberto — só confirme se o teste passou).
