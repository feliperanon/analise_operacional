# 🔧 Guia de Instalação e Setup de Desenvolvimento

Este documento detalha todos os passos necessários para configurar o ambiente de desenvolvimento do projeto **Análise Operacional**.

---

## 📋 Pré-requisitos

| Ferramenta | Versão Mínima | Descrição |
|------------|---------------|-----------|
| Python | 3.10+ | Linguagem principal do backend |
| Node.js | 18+ | Necessário para compilar TailwindCSS |
| PostgreSQL | 14+ | Banco de dados em produção |
| Git | 2.30+ | Controle de versão |

---

## 🐍 Dependências Python (Backend)

Instale todas as dependências **com o ambiente virtual ativado** (veja Passo 2):

```bash
pip install -r requirements.txt
```

Se o `pip` não for reconhecido (venv não ativado), use:

```bash
# Windows
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Linux/Mac
.venv/bin/python -m pip install -r requirements.txt
```

### Lista de Pacotes

| Pacote | Versão | Descrição |
|--------|--------|-----------|
| `fastapi` | 0.128.0 | Framework web assíncrono de alta performance |
| `uvicorn` | 0.40.0 | Servidor ASGI para rodar o FastAPI |
| `sqlmodel` | 0.0.31 | ORM que combina Pydantic + SQLAlchemy |
| `sqlalchemy` | 2.0.45 | Core do ORM, abstração de banco de dados |
| `pydantic` | 2.12.5 | Validação de dados e schemas |
| `pandas` | 2.3.3 | Manipulação de dados e importação de planilhas |
| `openpyxl` | 3.1.5 | Leitura/escrita de arquivos Excel (.xlsx) |
| `jinja2` | 3.1.6 | Motor de templates HTML |
| `python-multipart` | 0.0.21 | Upload de arquivos via formulários |
| `itsdangerous` | 2.2.0 | Assinatura segura de dados (sessões) |
| `psycopg2-binary` | 2.9.11 | Driver PostgreSQL para Python |
| `python-dotenv` | 1.2.1 | Carregamento de variáveis de ambiente (.env) |
| `tzdata` | latest | Dados de timezone (necessário no Windows) |

---

## 📦 Dependências Node.js (Frontend/CSS)

Instale as dependências de desenvolvimento com:

```bash
npm install
```

### Lista de Pacotes (devDependencies)

| Pacote | Versão | Descrição |
|--------|--------|-----------|
| `tailwindcss` | 3.4.17 | Framework CSS utility-first |
| `autoprefixer` | 10.4.20 | Adiciona prefixos CSS automaticamente |
| `postcss` | 8.4.49 | Processador de CSS |

### Scripts Disponíveis

```bash
# Compilar CSS uma vez (produção)
npm run build:css

# Modo watch (desenvolvimento) - recompila ao salvar
npm run watch:css
```

---

## 🧩 Extensões Recomendadas para VS Code

Para melhor produtividade, instale as seguintes extensões:

### Essenciais

| Extensão | ID | Descrição |
|----------|-----|-----------|
| **Python** | `ms-python.python` | Suporte completo a Python |
| **Pylance** | `ms-python.vscode-pylance` | IntelliSense avançado para Python |
| **Python Debugger** | `ms-python.debugpy` | Debug de código Python |
| **Jinja** | `wholroyd.jinja` | Syntax highlighting para templates Jinja2 |
| **Tailwind CSS IntelliSense** | `bradlc.vscode-tailwindcss` | Autocomplete de classes Tailwind |

### Recomendadas

| Extensão | ID | Descrição |
|----------|-----|-----------|
| **SQLite Viewer** | `qwtel.sqlite-viewer` | Visualizar banco SQLite no editor |
| **Thunder Client** | `rangav.vscode-thunder-client` | Testar APIs REST (alternativa ao Postman) |
| **GitLens** | `eamodio.gitlens` | Git avançado com histórico inline |
| **Error Lens** | `usernamehw.errorlens` | Mostra erros inline no código |
| **Prettier** | `esbenp.prettier-vscode` | Formatação automática de código |
| **Auto Rename Tag** | `formulahendry.auto-rename-tag` | Renomeia tags HTML automaticamente |
| **Path Intellisense** | `christian-kohler.path-intellisense` | Autocomplete de caminhos de arquivo |
| **DotENV** | `mikestead.dotenv` | Syntax highlighting para .env |

### Instalação Rápida via Terminal

```bash
# Essenciais
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension ms-python.debugpy
code --install-extension wholroyd.jinja
code --install-extension bradlc.vscode-tailwindcss

# Recomendadas
code --install-extension qwtel.sqlite-viewer
code --install-extension rangav.vscode-thunder-client
code --install-extension eamodio.gitlens
code --install-extension usernamehw.errorlens
code --install-extension esbenp.prettier-vscode
code --install-extension formulahendry.auto-rename-tag
code --install-extension christian-kohler.path-intellisense
code --install-extension mikestead.dotenv
```

---

## ⚙️ Configuração do VS Code

Adicione ao seu `settings.json` (Ctrl+Shift+P → "Preferences: Open Settings (JSON)"):

```json
{
    // Python
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "python.analysis.typeCheckingMode": "basic",
    
    // Editor
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "[python]": {
        "editor.defaultFormatter": "ms-python.python"
    },
    
    // Tailwind
    "tailwindCSS.includeLanguages": {
        "jinja-html": "html",
        "jinja": "html"
    },
    "tailwindCSS.emmetCompletions": true,
    
    // Files
    "files.associations": {
        "*.html": "jinja-html"
    }
}
```

---

## 🚀 Passo a Passo Completo

### 1. Clone o Repositório

```bash
git clone https://github.com/feliperanon/analise_operacional.git
cd analise_operacional
```

### 2. Configure o Ambiente Python

```bash
# Criar ambiente virtual
python -m venv .venv

# Ativar (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Ativar (Windows CMD)
.\.venv\Scripts\activate.bat

# Ativar (Linux/Mac)
source .venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

### 3. Configure o Frontend (TailwindCSS)

```bash
# Instalar dependências Node.js
npm install

# Compilar CSS (uma vez)
npm run build:css
```

### 4. Configure o Banco de Dados

Crie um arquivo `.env` na raiz:

```env
# Desenvolvimento (SQLite)
DATABASE_URL=sqlite:///database.db

# Produção (PostgreSQL)
# DATABASE_URL=postgresql://user:password@localhost/analise_operacional

# Debug (opcional)
DEBUG=false
```

### 5. Índices de Performance (opcional, PostgreSQL)

Se usar PostgreSQL em produção, aplique os índices para melhor desempenho:

```bash
# Execute o arquivo migration_add_indexes.sql no seu cliente PostgreSQL
# Exemplo com psql:
psql -h localhost -U seu_usuario -d analise_operacional -f migration_add_indexes.sql
```

Para SQLite (desenvolvimento), os índices não são obrigatórios.

### 6. Execute a Aplicação

```bash
# Windows (PowerShell)
.\run.ps1

# Windows (duplo clique)
# Use INICIAR_SISTEMA.bat

# Ou manualmente (com venv ativado)
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Ou sem ativar o venv (Windows)
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Acesse

- **Aplicação**: http://localhost:8000
- **API Docs (Swagger)**: http://localhost:8000/docs

### 8. Deploy em produção (Render)

Para publicar na nuvem, veja **[RENDER.md](RENDER.md)**.

---

## 🔍 Verificação de Instalação

Execute estes comandos para verificar se tudo está correto:

```bash
# Python (com venv ativado)
python --version  # Deve ser 3.10+

# Dependências Python
pip list | findstr fastapi  # Deve mostrar fastapi 0.128.0
# No PowerShell: pip list | Select-String fastapi

# Node.js
node --version  # Deve ser 18+

# TailwindCSS
npx tailwindcss --help  # Deve mostrar as opções

# Banco de dados (teste iniciando o servidor)
.\run.ps1  # Se subir sem erros, a conexão está ok
# Para DB existente: python check_schema.py
```

---

## ❓ Solução de Problemas

### Erro: "pip não é reconhecido"

Ative o ambiente virtual antes de usar `pip`, ou use o caminho completo:

```bash
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Erro: "ModuleNotFoundError: No module named 'xxx'"

```bash
pip install -r requirements.txt
```

### Erro: "Cannot find module 'tailwindcss'"

```bash
npm install
```

### Erro: "No timezone found"

```bash
pip install tzdata
```

### Erro de conexão com PostgreSQL

Verifique se:
1. O PostgreSQL está rodando
2. O `DATABASE_URL` está correto no `.env`
3. O usuário tem permissão no banco

---

**Última atualização:** Janeiro 2026
