# 🚀 Deploy no Render

Guia para publicar o **Análise Operacional** no [Render.com](https://render.com). Mantido atualizado para refletir as melhores práticas do Render e uso **API-First**.

---

## Para usuários API-First

O app é **API-First** (FastAPI). Após o deploy, use a mesma base URL para interface web e API:

| Recurso | URL |
|--------|-----|
| **App (web)** | `https://<seu-servico>.onrender.com` |
| **Documentação interativa (Swagger)** | `https://<seu-servico>.onrender.com/docs` |
| **Documentação alternativa (ReDoc)** | `https://<seu-servico>.onrender.com/redoc` |
| **OpenAPI JSON** | `https://<seu-servico>.onrender.com/openapi.json` |

- Todas as rotas da aplicação web consomem dados via **API REST**; o mesmo backend serve HTML e JSON.
- Para integrações externas, use `APP_BASE_URL` (ex.: `https://analise-operacional-xxxx.onrender.com`) como base e consulte `/docs` para os endpoints disponíveis.

---

## Pré-requisitos

- Conta no [Render](https://render.com) (grátis)
- Repositório no GitHub com o código
- Push do `render.yaml` para o repositório

---

## Opção 1: Blueprint (recomendado)

### Passo 1: Push do render.yaml

Garanta que o `render.yaml` está no repositório:

```bash
git add render.yaml
git commit -m "Add Render blueprint"
git push origin main
```

### Passo 2: Conectar no Render

1. Acesse [dashboard.render.com](https://dashboard.render.com)
2. **New +** → **Blueprint**
3. Conecte o GitHub e selecione o repositório `analise_operacional`
4. Render detecta o `render.yaml` e mostra os recursos (Web Service + PostgreSQL)

### Passo 3: Informar variáveis

O Blueprint pede valores para:

| Variável | O que colocar |
|----------|---------------|
| **ADMIN_EMAIL** | E-mail do admin (ex: admin@empresa.com) |
| **ADMIN_PASS** | Senha do admin (evite `admin` / vazio) |
| **APP_BASE_URL** | Deixe em branco na primeira vez |
| **IMPORT_AUTH_PASSWORD** | Senha para importação em datas ≠ hoje (obrigatória no Render) |

### Passo 4: Deploy

Clique em **Apply** e aguarde o deploy (cerca de 5–10 minutos).

### Passo 5: Configurar APP_BASE_URL

Após o deploy:

1. Vá em **Dashboard** → seu Web Service → **Environment**
2. Adicione ou edite:
   - **Key:** `APP_BASE_URL`
   - **Value:** `https://analise-operacional-xxxx.onrender.com` (sua URL exata)

---

## Opção 2: Manual (sem Blueprint)

### 1. Criar PostgreSQL

1. **New +** → **PostgreSQL**
2. Nome: `analise-db`
3. Região: `Oregon (US West)` ou a mais próxima
4. Plano: **Free** (teste) ou **Starter** (produção)
5. **Create Database**
6. Copie a **Internal Database URL** (connection string)

### 2. Criar Web Service

1. **New +** → **Web Service**
2. Conecte o repositório e selecione `analise_operacional`
3. Configure:

| Campo | Valor |
|-------|-------|
| **Name** | analise-operacional |
| **Region** | Oregon (ou próxima) |
| **Branch** | main |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |

### 3. Variáveis de ambiente

Em **Environment** do Web Service, adicione:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | Cole a Internal Database URL do PostgreSQL |
| `SECRET_KEY` | Gere uma chave segura |
| `REQUIRE_RENDER_DB` | `true` |
| `ADMIN_EMAIL` | Seu e-mail de admin |
| `ADMIN_PASS` | Senha do admin |
| `APP_BASE_URL` | `https://seu-servico.onrender.com` (preencher depois do deploy) |
| `IMPORT_AUTH_PASSWORD` | Senha obrigatória para importação em datas diferentes de hoje |
| `ENV` / `ENVIRONMENT` | Opcional: `production` |
| `DEBUG` | `false` em produção |

Variáveis adicionais e comentários para desenvolvimento local: veja `.env.example`.
No Render, `RENDER=true` é definido automaticamente no Web Service e pode ser usado para ajustes de produção, como proxy headers, pool do banco e validações obrigatórias de ambiente.

### Segurança e segredos

- Não commite `DATABASE_URL`, senhas SMTP, chaves de API nem `SECRET_KEY`.
- Não publique prints do painel com valores visíveis nem cole credenciais em chats ou issues.
- Se houver vazamento: altere a senha do Postgres no Render, regenere `SECRET_KEY`, revogue senha de app do Gmail e chaves de API, e defina um novo `IMPORT_AUTH_PASSWORD`.

### 4. Deploy

Clique em **Create Web Service**.

---

## ⚠️ Importante

### Banco gratuito (Free)

- **30 dias** de uso
- 1 GB de armazenamento
- Após 30 dias, os dados são apagados se não houver upgrade
- Ideal para testes, não para produção

### Plano pago (produção)

Para produção, use PostgreSQL **Starter** ou superior em **Dashboard** → **analise-db** → **Settings** → **Change Plan**.

---

## URLs (resumo)

| Uso | URL |
|-----|-----|
| App (web) | `https://analise-operacional-xxxx.onrender.com` |
| API Docs (Swagger) | `https://analise-operacional-xxxx.onrender.com/docs` |
| ReDoc | `https://analise-operacional-xxxx.onrender.com/redoc` |
| OpenAPI | `https://analise-operacional-xxxx.onrender.com/openapi.json` |

---

## Solução de problemas

### Erro 503 ou timeout

No plano Free o serviço dorme após ~15 min de inatividade. O primeiro acesso pode levar 30–60 s para acordar.

### Erro de conexão com o banco

- Verifique se `DATABASE_URL` está correto
- Use a **Internal Database URL** (não a External) no mesmo region

### Migrations/índices

O app cria as tabelas na subida. Para índices extras (PostgreSQL):

```bash
# Conecte via psql com a External Database URL do Render
psql "postgresql://..." -f migration_add_indexes.sql
```

---

## Manter o Render atualizado

- **Dashboard**: [dashboard.render.com](https://dashboard.render.com) — verificar planos, logs e variáveis de ambiente.
- **Documentação Render**: [render.com/docs](https://render.com/docs) — mudanças em Blueprint, runtimes e PostgreSQL.
- **API-First**: Este projeto expõe `/docs` e `/openapi.json`; integrações e usuários API-First devem usar `APP_BASE_URL` como base e consultar a documentação OpenAPI.
- **Blueprint (`render.yaml`)**: Ao alterar `render.yaml`, faça push para o branch conectado; o Render aplica as mudanças no próximo deploy.
