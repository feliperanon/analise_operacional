# 📊 Análise Operacional

Sistema de gestão inteligente para operações logísticas e controle de fluxo de colaboradores. Projetado para otimizar a alocação de equipes, monitorar KPIs em tempo real e fornecer insights operacionais detalhados.

![Status do Projeto](https://img.shields.io/badge/Status-Em_Desenvolvimento-blue)
![Python](https://img.shields.io/badge/Python-3.10+-yellow)
![FastAPI](https://img.shields.io/badge/FastAPI-0.95+-green)

## 🚀 Funcionalidades Principais

### 1. ⚡ Fluxo Operacional Inteligente (Smart Flow)
O coração da operação. Uma interface visual interativa para gestão em tempo real:
- **Gestão Visual**: Cards de setores (Recebimento, Seleção, Câmara Fria, Expedição) com indicadores de meta vs. realizado.
- **Alocação Dinâmica**: Arraste e solte colaboradores entre equipes? (Futuro) / Seleção rápida de sub-setores (Doca 1, Linha A, etc.).
- **Barra de KPIs**: Monitoramento instantâneo de Headcount, Vagas em Aberto, Absenteísmo e Produção (Tonelagem).
- **Status Sincronizados**: Controle de Férias, Atestados e Afastamentos que sincronizam automaticamente com o banco de dados.
- **Layout Responsivo**: Adaptado para visualização em telas únicas ou monitores de gestão.

### 2. 👥 Gestão de Colaboradores e Férias
- **Cadastro Completo**: Matrícula, Nome, Função, Turno e Centro de Custo.
- **Módulo de Férias Global**:
    - Agendamento individual de férias com feedback visual.
    - **Importação em Massa**: Ferramenta para colagem direta do Excel (Matrícula, Início, Fim) para atualizar múltiplos colaboradores de uma vez.
- **Histórico Automático**: Mudanças de status (Férias, Afastado, Ativo) geram eventos automáticos na timeline do colaborador.
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

**Frontend**
- **Templating**: Jinja2 (Renderização Server-Side)
- **Estilização**: TailwindCSS (Utility-first CSS, Foco em Dark Mode/Slate Theme)
- **Interatividade**: Vanilla JavaScript (Leve e rápido)
- **Ícones**: SVG (Lucide/Feather style)
- **Relatórios**: Geração de HTML/PDF otimizado para impressão/exportação.

## 📦 Instalação e Execução

### Pré-requisitos
- Python instalado.
- Gerenciador de pacotes `pip`.

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

4. **Execute a aplicação**
   Você pode usar o script facilitador ou o comando direto:

   **Opção A (Script Powershell):**
   ```powershell
   .\run.ps1
   ```

   **Opção B (Manual):**
   ```bash
   uvicorn main:app --reload
   ```

5. **Acesse no Navegador**
   - Aplicação: `http://localhost:8000`
   - Documentação Interativa (Swagger): `http://localhost:8000/docs`

## 📂 Estrutura de Pastas

```
analise_operacional/
├── main.py              # Aplicação Principal (Rotas e Configuração)
├── models.py            # Modelos de Dados (DB Schema)
├── database.py          # Conexão com Banco de Dados
├── requirements.txt     # Dependências do Projeto
├── run.ps1              # Script de Inicialização
│
├── templates/           # Arquivos HTML (Jinja2)
│   ├── base.html        # Layout Base (Sidebar, Header)
│   ├── smart_flow.html  # Página do Fluxo Inteligente
│   ├── employees.html   # Gestão de Colaboradores
│   ├── employee_detail.html # Detalhes do Colaborador
│   ├── report_pdf.html  # Modelo de Relatório PDF
│   └── index.html       # Dashboard
│
└── static/              # Arquivos Estáticos (CSS, JS, Imagens)
```

## 🤝 Contribuição

1. Faça um Fork do projeto
2. Crie uma Branch para sua Feature (`git checkout -b feature/IncrívelFeature`)
3. Faça o Commit de suas mudanças (`git commit -m 'Add some IncrívelFeature'`)
4. Faça o Push para a Branch (`git push origin feature/IncrívelFeature`)
5. Abra um Pull Request

---
**Desenvolvido por Felipe Ranon Marinho Pires**
