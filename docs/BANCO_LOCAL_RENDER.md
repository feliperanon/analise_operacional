# Usar banco do Render no servidor local

Para ver os **dados do Render** (Postgres) quando rodar o app em `127.0.0.1:8000`:

## 1. Obter a URL do Postgres no Render

1. Acesse [dashboard.render.com](https://dashboard.render.com) e faça login.
2. Abra o **serviço** que tem o banco (PostgreSQL).
3. Em **Connections** (ou na aba do banco), copie a **External Database URL** (não use Internal se estiver fora da Render).
   - Formato: `postgres://usuario:senha@host:porta/nome_do_banco?sslmode=require`
   - O Render às vezes mostra como `postgres://`; o código aceita e converte para `postgresql://` se precisar.

## 2. Configurar o `.env` na pasta do projeto

Na pasta `C:\Projetos\NL`, edite (ou crie) o arquivo **`.env`** e defina:

```env
# URL do Postgres do Render (cole a External Database URL aqui)
DATABASE_URL=postgresql://usuario:senha@host.render.com:5432/nome_banco?sslmode=require

# Importante: NÃO forçar SQLite; deixe comentado ou false para usar o Render
# FORCE_LOCAL_DB=false
```

Ou, se já existir `FORCE_LOCAL_DB=true`, **comente ou mude para false**:

```env
# FORCE_LOCAL_DB=true
FORCE_LOCAL_DB=false
```

Assim o app deixa de usar `database.db` e tenta conectar no Postgres do Render.

## 3. Reiniciar o servidor

Pare o uvicorn (Ctrl+C) e suba de novo:

```powershell
cd c:\Projetos\NL
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

No log deve aparecer algo como:

- `DATABASE URL DETECTADA: postgresql://...` (e **não** `sqlite:///database.db`).

Se aparecer `sqlite` ou `local_forced`, o `.env` ainda está com `FORCE_LOCAL_DB=true` ou a `DATABASE_URL` não está definida/carregada.

## 4. Voltar a usar só SQLite local

Para usar de novo apenas o banco local:

```env
FORCE_LOCAL_DB=true
```

Ou comente/remova a `DATABASE_URL` (e deixe `FORCE_LOCAL_DB=true`). Reinicie o uvicorn.

---

**Resumo:** Coloque a URL do Postgres do Render em `DATABASE_URL` e garanta que `FORCE_LOCAL_DB` não está como `true`. Reinicie o servidor.
