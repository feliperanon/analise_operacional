# Prompt Master — BI Avaliação de Motoristas

> **Contexto:** Dashboard BI para avaliação de motoristas com meta mensal de devolução < 2% para premiação. Sistema deve integrar dados de Route, Devolucao, Employee e delivery_vehicle_plate.

---

## Personas de atuação

Atue simultaneamente como:

1. **Engenheiro de Produção** — eficiência operacional, tempos, sequenciamento, variabilidade, causas raiz técnicas
2. **Gestor de Pessoas** — desempenho individual, motivação, metas, feedback, reconhecimento, padrões comportamentais
3. **Especialista em Logística** — rotas, veículos, peso, quantidade, SLA, custos operacionais, relativização
4. **Premeditador (Analista Preditivo)** — tendências, anomalias, correlações, riscos futuros, variáveis influenciadoras

---

## Objetivos do BI

1. **Avaliar elegibilidade à premiação** — meta mensal < 2% de devolução
2. **Mapear performance** — motorista mais lento, mais rápido, alta/baixa devolução
3. **Analisar causas** — motivos por motorista, influência do caminhão (placa), responsabilidade (Mercado/Comercial/Logística)
4. **Identificar padrões temporais** — dia da semana com mais devoluções
5. **Sistema de inteligência** — interpretar oscilações motorista vs caminhão, relativizar métricas
6. **Relativização** — quantidade × peso × devolução; relativização por caminhão

---

## Variáveis disponíveis (base de dados)

| Origem | Variáveis |
|--------|-----------|
| Route | date, shift, employee_id, client_id, tonnage, valor_financeiro, devolucao_volume, valor_devolucao, delivery_status, delivery_vehicle_plate, delivery_return_reason, delivery_return_category, delivery_started_at, delivery_finished_at, delivery_reopen_count |
| Devolucao (manual) | data_romaneio, motorista_id, client_id, motivo_id, responsabilidade_id, valor, cluster, acima_300 |
| Employee | name, work_shift, admission_date, status |
| DevolucaoMotivo / DevolucaoResponsabilidade | motivo, responsabilidade |

---

## Dimensões e análises obrigatórias

### 1. Desempenho individual

- Taxa de devolução % (qtd e valor) — meta < 2%
- Eficiência entregas/planejadas
- Tempo médio (duração) — identificar mais lento e mais rápido
- Motoristas com alto índice de devolução (> 5%, > 10%, críticos)
- Elegibilidade à premiação mensal (sim/não, com % atual)

### 2. Motivos por motorista

- Breakdown por motorista × motivo × qtd × valor
- % de devolução sobre valor real por motorista
- Responsabilidade (Mercado / Comercial / Logística) por motorista
- Top motivos recorrentes por motorista (identificar padrões comportamentais)

### 3. Influência do caminhão (placa)

- Performance por placa — taxa devolução, tempo médio, paradas
- Comparar mesmo motorista em caminhões diferentes (quando houver troca)
- Relativização: caminhão mais lento, mais rápido, com mais devoluções
- Correlação motorista × caminhão (qual combinação performa melhor/pior)

### 4. Padrões temporais

- Dia da semana com mais devoluções (Seg–Dom)
- Dia da semana com menor tempo médio / maior tempo médio
- Tendência mensal, semanal
- Sazonalidade (início/fim de mês, feriados próximos se houver dados)

### 5. Relativização quantidade × peso × devolução

- Devolução por parada vs por kg vs por valor (R$)
- Motoristas com alta quantidade mas baixo peso — perfil leve vs pesado
- Motoristas com alto valor devolvido mas baixa quantidade — devoluções concentradas em pedidos de alto valor
- Índices normalizados: devolução / parada, devolução / tonelada, devolução / R$ entregue

### 6. Relativização por caminhão

- Paradas/placa, kg/placa, devoluções/placa
- Valor devolvido / valor entregue por placa
- Tempo médio por placa vs média geral

### 7. Sistema de inteligência — interpretação de oscilações

- **Oscilação motorista:** desvio padrão da taxa de devolução do motorista ao longo do tempo; alerta se variância alta
- **Oscilação caminhão:** mesma métrica por placa; detectar se veículo específico está associado a piora
- **Separação efeito motorista vs caminhão:** quando motorista usa vários caminhões, comparar desempenho por veículo
- **Anomalias:** picos de devolução inesperados; quedas de performance súbitas
- **Benchmark dinâmico:** comparar motorista vs média dos pares (mesmo turno, mesma região se houver)

---

## Ideias adicionais (premeditador + gestão de pessoas + produção)

### Gestão de pessoas

- **Histórico de metas:** evolução mês a mês para ver tendência de melhora/piora
- **Score composto:** combinar devolução %, tempo, reaberturas em um único índice (ex: 0–100)
- **Ranking de consistência:** motoristas mais estáveis vs oscilantes
- **Cobertura de meta:** “faltam X% para atingir meta de 2%” — motivacional
- **Comparação com período anterior:** “este mês vs mês passado” por motorista

### Logística

- **Intensidade de rota:** paradas/dia, kg/parada — rotas mais pesadas podem ter mais devolução
- **Janela de entrega:** se houver dados de horário, verificar se devoluções se concentram em horários específicos
- **Cliente recorrente:** motoristas que atendem clientes com histórico de devolução — fator externo

### Produção

- **Eficiência tempo/parada:** min/parada — quem é mais produtivo em tempo
- **Reaberturas:** indicador de problema operacional (não concluiu de primeira)
- **Devoluções acima de R$300:** % de linhas de alto valor — impacto financeiro concentrado

### Preditivo

- **Previsão de elegibilidade:** probabilidade de manter < 2% até fim do mês dado desempenho até hoje
- **Risco de saída da meta:** alerta antecipado quando tendência aponta para > 2%
- **Correlações:** peso médio da rota × devolução; quantidade de paradas × tempo; etc.
- **Padrões de dia da semana:** “quartas-feiras costumam ter +X% devolução” — hipótese a testar

---

## Requisitos técnicos do BI

- Nova página/rota dedicada (ex: `/bi/motorista` ou `/bi/driver-eval`)
- Período filtrado (data inicial / final) — mínimo mensal para meta
- Filtros: turno, motorista, placa
- Visões: executivo (KPIs + elegibilidade), tático (rankings, gráficos), drill-down operacional
- Exportação CSV/XLSX/PDF
- Integração com mesma base de dados do BI Delivery (`Route`, `Devolucao`, `Employee`)

---

## Métricas-chave a exibir

| KPI | Fórmula | Benchmark |
|-----|---------|-----------|
| Taxa devolução % | (devoluções / paradas planejadas) × 100 | < 2% meta premiação |
| Tempo médio rota | média(duration_m) | menor = melhor (contexto-dependente) |
| Eficiência | entregues / planejadas × 100 | > 95% |
| Valor devolvido / valor real | (R$ devolvido / R$ realizado) × 100 | menor = melhor |
| Oscilação (σ) | desvio padrão da taxa devolução do motorista no período | menor = mais estável |
| Elegibilidade premiação | sim se taxa < 2% no mês | binário |

---

## Output esperado

1. Dashboard com:
   - Bloco de elegibilidade à premiação (motoristas elegíveis vs não elegíveis)
   - Ranking motorista mais lento / mais rápido
   - Gráfico motivos × motorista
   - Gráfico dia da semana × devoluções
   - Tabela motorista × caminhão com relativização
   - Bloco de “inteligência”: oscilações, anomalias, recomendações
   - Relativização quantidade × peso × devolução (gráficos/tabelas)
2. Sistema interpretativo: textos automáticos explicando oscilações e sugerindo ações
3. Compatibilidade com estrutura existente (base.html, bi_delivery como referência)

---

## Comandos de ativação do prompt

Ao iniciar a implementação, use:

> “Atue como Engenheiro de Produção, Gestor de Pessoas, Especialista em Logística e Premeditador. Implemente o BI de Avaliação de Motoristas conforme PROMPT_BI_MOTORISTA.md, considerando meta de premiação < 2% de devolução mensal, análise de motivos por motorista, influência do caminhão, dia da semana de devoluções, relativização quantidade × peso × devolução e por caminhão, e sistema de inteligência para interpretação de oscilações motorista vs caminhão.”
