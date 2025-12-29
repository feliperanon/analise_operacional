
# Dashboard de Inteligência de Pessoas (Gestão de Pessoas 2.0)

## Objetivo
Criar um painel de "Inteligência de Gestão de Pessoas" estratégico que transforme dados operacionais em insights acionáveis de RH. O dashboard cobrirá 10 pilares principais, incluindo indicadores básicos, análise por função, tempo de casa, demografia e inteligência preditiva.

## Revisão Necessária do Usuário
> [!IMPORTANT]
> **Preenchimento de Histórico (Backfill)**: Criaremos um script `backfill_events.py` para ler as Operações Diárias passadas e gerar registros de `Evento` para faltas e atestados. Isso é uma ação única, mas crítica para que o dashboard mostre tendências históricas imediatamente.

## Mudanças Propostas

### Backend (`main.py`)
#### [MODIFICAR] `main.py`
- **Atualizações em `update_routine`**:
    - Adicionar lógica para detectar mudanças de status (Presente -> Falta/Atestado/Afastado) no `attendance_log`.
    - Criar automaticamente registros de `Evento` (tipo: `falta`, `atestado`, `afastamento`) quando esses status ocorrerem.
    - Garantir que não sejam criados eventos duplicados para o mesmo dia/colaborador.
- **Novo Endpoint**: `GET /people_intelligence`
    - Agrega dados para os 10 pilares:
        1.  **Básico**: Contagem de tipos de `Evento` (falta, atestado) por colaborador.
        2.  **Setor/Função**: Agrupamento por `employee.cost_center` e `employee.role`.
        3.  **Tempo de Casa**: Correlação de anomalias com `admission_date`.
        4.  **Demografia**: Estatísticas de Idade/Gênero (se disponível).
        5.  **Saúde**: Análise de tendência de eventos de `atestado`.
        6.  **Impacto**: Estimativa de horas perdidas (Faltas * 8h).
        7.  **Disciplina**: Eventos de advertência.
    - Retorna uma estrutura JSON ou renderiza o template diretamente com o contexto.

### Banco de Dados
#### [NOVO] `backfill_events.py`
- Script para iterar sobre todas as linhas de `DailyOperation`.
- Analisar o `attendance_log` de cada dia.
- Criar registros de `Evento` faltantes para análise histórica.

### Frontend (`templates/people_intelligence.html`)
#### [NOVO] `templates/people_intelligence.html`
- Um layout de dashboard sofisticado alinhado com a estética "Dark/Premium" do usuário.
- **Seções**:
    - **Radar Geral**: Números grandes (Absenteísmo %, Total Faltas).
    - **Top Ofensores**: Rankings (Quem mais falta, Quem mais apresenta atestado).
    - **Análise Setorial**: Mapa de calor/Grade dos setores.
    - **Insights**: Textos de alerta (ex: "Setor X está com absenteísmo 20% acima da média").
- Uso de CSS Grid/Flexbox para layout. Evitar bibliotecas de gráficos pesadas externas; usar barras CSS simples ou SVG para visualização.

## Plano de Verificação
### Automatizado
- Executar `backfill_events.py` e verificar se a contagem de `Evento` aumenta.
- Chamar `GET /people_intelligence` e verificar a estrutura JSON/renderização HTML.

### Manual
- **Verificação Visual**: Abrir a nova página.
- **Validação de Dados**: Comparar "Total Faltas" no dashboard com contagens manuais conhecidas para um colaborador de amostra.
