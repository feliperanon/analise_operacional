# Servidor local usando dados do Render

Para o servidor local (`http://127.0.0.1:8000`) usar o **mesmo banco** que o app no Render:

## 1. Copiar a URL do banco no Render

1. Acesse [dashboard.render.com](https://dashboard.render.com).
2. Abra o **Web Service** do app (ex.: analise-operacional).
3. Vá em **Environment**.
4. Copie o valor de **`DATABASE_URL`** (Internal Database URL do Postgres).

Se você não vir `DATABASE_URL` nas variáveis do serviço, pegue a **Internal Database URL** no painel do banco PostgreSQL vinculado ao serviço.

## 2. Colar no `.env` local

1. Na raiz do projeto, abra o arquivo **`.env`**.
2. Na linha `DATABASE_URL=`, **cole** a URL que você copiou (sem aspas).
   - Exemplo: `DATABASE_URL=postgresql://usuario:senha@dpg-xxxxx.oregon-postgres.render.com/nome_do_banco`
3. Salve o arquivo.
4. Confirme que está assim: `FORCE_LOCAL_DB=false` (já está no `.env` criado).

## 3. Reiniciar o servidor

Pare o servidor (Ctrl+C) e suba de novo:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 4. Conferir

Abra no navegador:

**http://127.0.0.1:8000/api/debug/db-info**

- **`database_source`** deve ser **`render`** (não `local` nem `local_fallback`).
- **`url_obfuscated`** deve começar com `postgresql://`.
- **`counts`** deve mostrar os mesmos volumes de dados que no Render.

Se aparecer `local_fallback`, a conexão com o Postgres do Render falhou (URL errada, rede ou firewall). Verifique a URL e se o banco aceita conexões externas.
