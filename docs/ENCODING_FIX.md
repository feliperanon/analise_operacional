# Correção Estrutural de Encoding UTF-8

## Diagnóstico Técnico: Causa do Erro "Ã§Ã£"

### O que é "Ã§Ã£"?
É **mojibake** (texto corrompido por mistura de encodings): a string UTF-8 `"ção"` (bytes `C3 A7 C3 A3 6F`) foi **interpretada como Latin-1/ISO-8859-1** e salva novamente. Cada byte `C3`, `A7`, `A3` vira um caractere Latin-1: `Ã`, `§`, `£`.

| Original (UTF-8) | Interpretado errado (Latin-1) | Resultado visível |
|------------------|------------------------------|-------------------|
| ç (U+00E7)       | Ã + §                        | Ã§                |
| ã (U+00E3)       | Ã + £                        | Ã£                |
| ão              | Ã£o                          | "Ã£o" em vez de "ão" |

### Causa raiz no projeto
Os **arquivos Python (.py) contêm string literais já corrompidas no disco**. Quando o editor salvou o arquivo (possivelmente com encoding Latin-1/Windows-1252 ou em ambiente que não preservou UTF-8), os caracteres acentuados foram gravados como sequências erradas. O runtime apenas lê o que está no arquivo.

### Não é problema de
- Configuração do navegador
- Headers HTTP (o middleware já adiciona `charset=utf-8`)
- Banco de dados (SQLite/Postgres usam UTF-8)
- Meta charset nos templates (`<meta charset="UTF-8">` está correto)

### É problema de
- **Fonte dos dados**: strings nos arquivos .py estão corrompidas
- **Ambiente de edição**: risco de reincidência se o editor/IDE não usar UTF-8
- **Pipeline de arquivos**: falta de padronização explícita em todo o projeto

---

## Checklist de Verificação (UTF-8 Ponta a Ponta)

### 1️⃣ Frontend (HTML / Templates / JS)
- [ ] `<meta charset="UTF-8">` em base.html ou layout principal
- [ ] Arquivos `.html`, `.js`, `.jinja` salvos em UTF-8 (sem BOM)
- [ ] `Content-Type: text/html; charset=utf-8` na resposta HTTP
- [ ] Nenhum `charset` alternativo em tags `<script>` ou `<link>`
- [ ] Editor/IDE configurado para UTF-8 (EditorConfig, settings.json)

### 2️⃣ Backend (FastAPI / Python)
- [ ] `# -*- coding: utf-8 -*-` no topo dos .py (Python 3 já assume, mas é boa prática)
- [ ] String literais em português com caracteres corretos (ç, ã, é, etc.)
- [ ] `JSONResponse` / serialização JSON sem perda de encoding
- [ ] Leitura de arquivos com `encoding="utf-8"`
- [ ] Logs e `RotatingFileHandler` com `encoding="utf-8"`

### 3️⃣ Servidor / Ambiente
- [ ] Uvicorn/Gunicorn: variável `PYTHONIOENCODING=utf-8` (produção)
- [ ] Windows: `chcp 65001` ou terminal com UTF-8
- [ ] Render/Heroku: `LANG=C.UTF-8` ou equivalente
- [ ] Servidor web (nginx, etc.): não reencodar respostas

### 4️⃣ Banco de Dados
- [ ] SQLite: UTF-8 nativo; conexão sem conversão
- [ ] PostgreSQL: database criado com `ENCODING 'UTF8'`
- [ ] Engine SQLAlchemy com `connect_args` para `client_encoding=UTF8` (Postgres)
- [ ] Migrations e seeds salvos em UTF-8

---

## Configurações Aplicadas

| Camada | Arquivo | Ajuste |
|--------|---------|--------|
| DB     | database.py | `connect_args` com `client_encoding=UTF8` (Postgres) |
| App    | main.py | Jinja2 com `bytecode_cache` e `encoding="utf8"` |
| Middleware | main.py | `charset=utf-8` em Content-Type para HTML/JSON |
| Projeto | .editorconfig | `charset = utf-8` para todos os textos |
| Correção | scripts/fix_mojibake.py | Script único para reparar arquivos .py já corrompidos |

---

## Execução da Correção

1. **Configurações já aplicadas**: database, middleware, EditorConfig.
2. **Rodar o script de correção** (uma vez):
   ```bash
   pip install ftfy   # opcional, mas recomendado para corrigir mojibake complexo
   python scripts/fix_mojibake.py
   ```
3. **Validar** que botões e textos dinâmicos exibem corretamente.
4. **Impedir recorrência**: EditorConfig + UTF-8 em editores e pipelines.
