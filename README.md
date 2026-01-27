# 📊 Análise Operacional

Sistema de gestão inteligente para operações logísticas e controle de fluxo de colaboradores. Projetado para otimizar a alocação de equipes, monitorar KPIs em tempo real e fornecer insights operacionais detalhados.

![Status do Projeto](https://img.shields.io/badge/Status-Em_Desenvolvimento-blue)
![Python](https://img.shields.io/badge/Python-3.10+-yellow)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95+-green)
![Performance](https://img.shields.io/badge/Performance-Otimizado-brightgreen)

## 🚀 Funcionalidades Principais

### 1. ⚡ Fluxo Operacional Inteligente (Smart Flow)

O coração da operação. Uma interface visual interativa para gestão em tempo real:

- **Gestão Visual**: Cards de setores (Recebimento, Seleção, Câmara Fria, Expedição) com indicadores de meta vs. realizado.
- **Alocação Dinâmica**: Arraste e solte colaboradores entre equipes? (Futuro) / Seleção rápida de sub-setores (Doca 1, Linha A, etc.).
- **Barra de KPIs**: Monitoramento instantâneo de Headcount, Vagas em Aberto, Absenteísmo e Produção (Tonelagem).
- **Status Sincronizados**: Controle de Férias, Atestados e Afastamentos que sincronizam automaticamente com o banco de dados.
- **Layout Mobile-First**: Interface responsiva com Sidebar adaptável, Bottom Sheet para ações rápidas e navegação fluida em dispositivos móveis.
- **Accordion e Listas Expansíveis**: Gestão de sub-setores otimizada para telas pequenas.
- **Arquitetura API-First**: Separação total entre dados (API REST) e apresentação (HTML/JS).

### 2. 👥 Gestão de Colaboradores e Férias

- **Cadastro Completo**: Matrícula, Nome, Função, Turno e Centro de Custo.
- **Módulo de Férias Global**:
  - Agendamento individual de férias com feedback visual.
  - **Importação em Massa**: Ferramenta para colagem direta do Excel (Matrícula, Início, Fim).
- **Histórico & Edição**: Mudanças de status (Férias, Afastado) geram eventos automáticos traduzidos. Edição completa de histórico (Tipo, Data, Texto) disponível.
- **Horário de Trabalho**: Exibição clara do turno/horário no detalhe do colaborador.
- **Filtros Inteligentes**: Busca rápida por nome, matrícula e visualização segmentada por turno.

### 3. 📈 Dashboard e Analytics

- Visão gerencial dos resultados operacionais.
- Gráficos de performance histórica.
- Relatórios de "Dia Crítico" e Rankings de Produtividade.

### 4. 📝 Diário de Operações e Relatórios

- **Registro Oficial**: Controle detalhado de ocorrências do turno (Chegada/Saída, Qualitativo).
- **Relatório PDF**: Geração automática de relatório de turno (`/routine/report`) contendo:
  - KPIs consolidados (Total, GAP, Tonelagem, Produtividade).
  - Lista de presença e ausências.
  - Insights automáticos: Aniversariantes e Vencimento de Contratos (45/90 dias).

## 🛠️ Tecnologias Utilizadas

**Backend**

- **Language**: Python 3.10+
- **Framework**: FastAPI (Alta performance, assíncrono)
- **Database**: SQLModel (Abstração sobre SQLAlchemy)
- **Banco de Dados**: PostgreSQL (Produção) / SQLite (Desenvolvimento)
- **Logging**: RotatingFileHandler com níveis otimizados (INFO em produção)

**Frontend**

- **Arquitetura**: API-First (Separação total de dados e apresentação)
- **Templating**: Jinja2 (Apenas estrutura HTML, sem lógica de negócio)
- **Estilização**: TailwindCSS (Utility-first CSS, Foco em Dark Mode/Slate Theme)
- **Interatividade**: Vanilla JavaScript (Modular, com fetch API)
- **Ícones**: SVG (Lucide/Feather style)
- **Relatórios**: Geração de HTML/PDF otimizado para impressão/exportação.

**Performance**

- **Logs Otimizados**: Sistema de rotação automática (5MB max, 3 backups)
- **Queries Indexadas**: 20+ índices em colunas críticas
- **Cache Inteligente**: Dados raramente alterados em memória
- **SQL Echo Condicional**: Apenas em modo DEBUG

## ⚡ Performance e Otimizações

### Ganhos Implementados

- 🚀 **2x-2.4x mais rápido** (50-140% de melhoria)
- 📉 **90% menos logs** gerados
- 💾 **Logs controlados** (rotação automática, sem crescimento infinito)
- ⚡ **Queries otimizadas** com índices em colunas críticas

### Arquitetura API-First

O sistema segue rigorosamente a arquitetura API-First:

- ✅ Templates HTML contêm **apenas estrutura e layout**
- ✅ Dados são **sempre carregados via API REST** (`fetch/axios`)
- ✅ JavaScript gerencia **todo o estado e lógica de negócio**
- ✅ Backend fornece **dados validados via Pydantic schemas**

### Sistema de Logs Inteligente

```python
# Logs otimizados com rotação automática
RotatingFileHandler(
    'logs.txt',
    maxBytes=5*1024*1024,  # 5 MB max
    backupCount=3  # Mantém 3 backups
)

# Nível INFO em produção, DEBUG apenas com flag explícita
LOG_LEVEL = logging.INFO  # (ou DEBUG se DEBUG=true)
```

### Índices de Banco de Dados

20+ índices criados em colunas frequentemente consultadas:

- `employee`: registration_id, status, work_shift, cost_center
- `dailyoperation`: date+shift, date
- `event`: employee_id, timestamp, type, category
- `route`: date+shift, employee_id, client_id

## 📦 Instalação e Execução

### Pré-requisitos

- Python 3.10+ instalado
- PostgreSQL (produção) ou SQLite (desenvolvimento)
- Gerenciador de pacotes `pip`

### Passo a Passo

1. **Clone o repositório**

   ```bash
   git clone https://github.com/feliperanon/analise_operacional.git
   cd analise_operacional
   ```

2. **Crie e ative um ambiente virtual**

   ```bash
   python -m venv .venv
   # Windows
   .\.venv\Scripts\activate
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Instale as dependências**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure o banco de dados (Opcional)**

   Crie um arquivo `.env` na raiz do projeto:

   ```env
   # PostgreSQL (Produção)
   DATABASE_URL=postgresql://user:password@localhost/dbname
   
   # SQLite (Desenvolvimento) - Padrão se não especificado
   # DATABASE_URL=sqlite:///database.db
   
   # Modo Debug (desabilitado por padrão)
   DEBUG=false

   # E-mail de manutencao (SMTP)
   # Necessario para enviar alertas de checklist e teste SMTP.
   # Microsoft 365: SMTP_HOST=smtp.office365.com / SMTP_PORT=587 / SMTP_TLS=true
   SMTP_HOST=smtp.seudominio.com
   SMTP_PORT=587
   SMTP_USER=usuario@seudominio.com
   SMTP_PASS=sua_senha
   SMTP_TLS=true
   SMTP_USE_SSL=false

   # Destinatarios padrao (opcional se cadastrados no painel)
   MAINTENANCE_EMAIL_TO=manutencao@empresa.com
   ```

   Use `.env.example` como base para a lista completa de variaveis.

5. **Aplique otimizações de índices (Recomendado)**

   ```bash
   # Windows
   .\apply_indexes.bat
   
   # Linux/Mac
   python apply_indexes.py
   ```

6. **Execute a aplicação**

   **Opção A (Script Powershell - Windows):**

   ```powershell
   .\run.ps1
   ```

   **Opção B (Manual):**

   ```bash
   uvicorn main:app --reload
   ```

7. **Acesse no Navegador**
   - Aplicação: `http://localhost:8000`
   - Documentação Interativa (Swagger): `http://localhost:8000/docs`

## 📂 Estrutura de Pastas

```
analise_operacional/
├── main.py                      # Aplicação Principal (Rotas e Configuração)
├── models.py                    # Modelos de Dados (DB Schema)
├── database.py                  # Conexão com Banco de Dados
├── requirements.txt             # Dependências do Projeto
├── run.ps1                      # Script de Inicialização
│
├── migration_add_indexes.sql    # Script de Índices (Performance)
├── apply_indexes.py             # Aplicador de Índices
├── apply_indexes.bat            # Script Batch (Windows)
│
├── templates/                   # Arquivos HTML (Jinja2)
│   ├── base.html                # Layout Base (Sidebar, Header)
│   ├── smart_flow.html          # Página do Fluxo Inteligente
│   ├── employees.html           # Gestão de Colaboradores
│   ├── employee_detail.html     # Detalhes do Colaborador
│   ├── report_pdf.html          # Modelo de Relatório PDF
│   └── index.html               # Dashboard
│
└── static/                      # Arquivos Estáticos (CSS, JS, Imagens)
    ├── css/                     # Estilos (TailwindCSS)
    └── js/                      # JavaScript Modular
        └── smart-flow/          # Módulos do Smart Flow
            ├── store.js         # Gerenciamento de Estado
            ├── api.js           # Comunicação com API
            ├── ui.js            # Renderização de UI
            └── events.js        # Handlers de Eventos
```

## 🔧 Scripts Úteis

### Aplicar Índices de Performance

```bash
# Windows
.\apply_indexes.bat

# Linux/Mac
python apply_indexes.py
```

### Executar em Modo Debug

```bash
# Ativar logs detalhados (SQL queries, DEBUG level)
# Edite .env:
DEBUG=true

# Reinicie o servidor
.\run.ps1
```

### Backup do Banco de Dados

```bash
# PostgreSQL
pg_dump -U user dbname > backup.sql

# SQLite
cp database.db database.db.backup_$(date +%Y%m%d_%H%M%S)
```

## 📊 Métricas de Performance

### Tempo de Resposta (Após Otimizações)

| Página | Tempo Médio | Status |
|--------|-------------|--------|
| `/smart-flow` | 0.8-1.2s | ✅ Otimizado |
| `/employees` | 0.4-0.8s | ✅ Otimizado |
| `/separacao` | 0.6s | ✅ Otimizado |
| APIs REST | 80-200ms | ✅ Otimizado |

### Logs

- **Tamanho máximo:** 5 MB (rotação automática)
- **Backups:** 3 arquivos mantidos
- **Taxa de crescimento:** ~20 KB/minuto (vs. ~187 KB/min antes)

## 🤝 Contribuição

1. Faça um Fork do projeto
2. Crie uma Branch para sua Feature (`git checkout -b feature/IncrívelFeature`)
3. Faça o Commit de suas mudanças (`git commit -m 'Add some IncrívelFeature'`)
4. Faça o Push para a Branch (`git push origin feature/IncrívelFeature`)
5. Abra um Pull Request

## 📝 Documentação Adicional

- **Análise de Erros:** Veja `docs/analise_erros_completa.md` para histórico de bugs e soluções
- **Plano de Otimização:** Veja `docs/plano_otimizacao_performance.md` para detalhes técnicos
- **Guia de Otimização:** Veja `docs/guia_otimizacao.md` para instruções passo a passo

## 🏆 Melhorias Recentes

### Janeiro 2026 (Refinamento Mobile)

- ✅ **Mobile-First Real**: Refatoração completa de layout para uso em celulares (Sidebar oculta, Headers adaptáveis).
- ✅ **Bottom Sheet Interativo**: Substituição de modais e menus desktop por painéis deslizantes inferiores.
- ✅ **Accordion em Gestão**: Sub-setores agora colapsáveis para melhor uso de espaço vertical.
- ✅ **Rastreamento de Atividades**: Logs precisos de início/fim e observações via interface touch.

### Melhorias Anteriores

- ✅ **Horário de Trabalho**: Módulo para exibição e gestão de escalas individuais.
- ✅ **Edição de Histórico**: Possibilidade de corrigir qualquer evento passado (Ex: Falta -> Atestado).
- ✅ **Blindagem Anti-500**: Proteção global de rotas.
- ✅ **Performance**: Ganho de 2x em velocidade.

---

**Desenvolvido por Felipe Ranon Marinho Pires**  
**Última atualização:** Janeiro 2026
