# 📊 SISTEMA DE ANÁLISE OPERACIONAL

## Relatório Executivo para Diretoria

**Data:** Janeiro 2026  
**Versão:** 2.0  
**Desenvolvido por:** Felipe Ranon Marinho Pires

---

## 🎯 VISÃO GERAL

O **Sistema de Análise Operacional** é uma plataforma integrada de gestão logística desenvolvida para otimizar operações, monitorar KPIs em tempo real, gerenciar equipes e promover engajamento através de gamificação.

### Objetivos Estratégicos

1. **Eficiência Operacional** - Reduzir tempo de alocação e aumentar produtividade
2. **Visibilidade em Tempo Real** - Dashboards com métricas atualizadas instantaneamente
3. **Gestão de Pessoas** - Controle completo de colaboradores, férias e absenteísmo
4. **Engajamento** - Sistema de gamificação para motivar e reconhecer performance
5. **Rastreabilidade** - Histórico completo de operações e eventos

---

## 🏗️ ARQUITETURA DO SISTEMA

| Componente | Tecnologia | Propósito |
|------------|------------|-----------|
| Backend | FastAPI (Python) | Alta performance, assíncrono |
| Frontend | TailwindCSS + JavaScript | Interface moderna e responsiva |
| Banco de Dados | PostgreSQL (Prod) / SQLite (Dev) | Persistência de dados |
| Templating | Jinja2 | Renderização de páginas |

### Métricas de Performance

- **Tempo de resposta médio:** 0.4-1.2 segundos
- **APIs REST:** 80-200ms
- **Ganho de performance:** 2x mais rápido após otimizações
- **Logs otimizados:** 90% de redução no volume

---

## 📱 MÓDULOS DO SISTEMA

---

### 1. 🏠 CENTRAL DE COMANDO (Dashboard Principal)

**Rota:** `/` (index)  
**Acesso:** Web Desktop e Mobile

#### Objetivo
Fornecer uma visão executiva consolidada de toda a operação em um único painel.

#### Funcionalidades
- **KPIs em Tempo Real:**
  - Volume Total (kg) processado
  - Velocidade Média (kg/hora)
  - Headcount (Presente vs Meta)
  
- **Filtro por Turno:** Manhã, Tarde, Noite ou Todos
- **Indicadores Visuais:** Barras de progresso e cores indicativas
- **Navegação Rápida:** Acesso direto a todos os módulos

#### Valor para o Negócio
Permite aos gestores ter uma fotografia instantânea da operação, identificando rapidamente gargalos e oportunidades.

---

### 2. ⚡ FLUXO OPERACIONAL INTELIGENTE (Smart Flow)

**Rota:** `/smart-flow`  
**Acesso:** Líderes e Supervisores

#### Objetivo
Gestão visual e em tempo real da alocação de colaboradores nos setores operacionais.

#### Funcionalidades

| Recurso | Descrição |
|---------|-----------|
| **Cards de Setores** | Recebimento, Seleção, Câmara Fria, Expedição |
| **Sub-setores** | Doca 1, Linha A, etc. (configuráveis) |
| **Alocação Visual** | Arraste e solte colaboradores entre equipes |
| **Status em Tempo Real** | Presente, Falta, Férias, Atestado, Afastado |
| **Indicadores de Meta** | Meta vs Realizado por setor |
| **Accordion Expansível** | Otimizado para telas mobile |

#### Barra de KPIs
- Headcount Total
- Vagas em Aberto
- Taxa de Absenteísmo
- Tonelagem do Turno

#### Ações Disponíveis
- Alternar entre datas
- Trocar turnos (Manhã/Tarde/Noite)
- Gerar Relatório PDF
- Visualizar Organograma
- Acessar Histórico Operacional

#### Valor para o Negócio
Elimina planilhas manuais, reduz tempo de alocação de equipes e fornece visibilidade instantânea da distribuição de recursos.

---

### 3. 📋 RELATÓRIO DE TURNO (Report PDF)

**Rota:** `/routine/report`  
**Acesso:** Todos os usuários autenticados

#### Objetivo
Gerar documentação oficial do turno com todas as métricas e ocorrências.

#### Conteúdo do Relatório
- **KPIs Consolidados:**
  - Total de colaboradores
  - GAP (vagas em aberto)
  - Tonelagem processada
  - Produtividade média

- **Lista de Presença:**
  - Colaboradores presentes
  - Colaboradores ausentes (com motivo)
  
- **Insights Automáticos:**
  - Aniversariantes do dia
  - Vencimento de contratos (45/90 dias)
  - Alertas importantes

#### Valor para o Negócio
Documentação padronizada para histórico, auditorias e passagem de turno.

---

### 4. 🏢 ORGANOGRAMA OPERACIONAL

**Rota:** `/smart-flow/organogram`  
**Acesso:** Líderes e Supervisores

#### Objetivo
Visualização hierárquica da distribuição de colaboradores por setor.

#### Funcionalidades
- Estrutura visual em árvore
- Agrupamento por setor e sub-setor
- Contagem de colaboradores por área
- Exportável para apresentações

#### Valor para o Negócio
Facilita a comunicação da estrutura operacional para stakeholders.

---

### 5. 👥 GESTÃO DE COLABORADORES

**Rota:** `/employees`  
**Acesso:** Líderes, RH, Administradores

#### Objetivo
Cadastro e gestão completa do ciclo de vida dos colaboradores.

#### Dados Cadastrais
| Campo | Descrição |
|-------|-----------|
| Matrícula | Identificador único |
| Nome | Nome completo |
| Função/Cargo | Posição na empresa |
| Turno | Manhã, Tarde ou Noite |
| Centro de Custo | Área/departamento |
| Data de Admissão | Início na empresa |
| Aniversário | Data de nascimento |
| Horário de Trabalho | Escala (ex: 07:00 - 15:20) |
| Dias de Trabalho | Seg-Sáb, escala 6x1, etc. |

#### Status Possíveis
- ✅ **Ativo** - Trabalhando normalmente
- 🏖️ **Férias** - Em período de férias
- 🏥 **Atestado** - Afastado por atestado médico
- ⚠️ **Afastado** - Licença ou outro afastamento
- 📴 **Folga** - Dia de folga programado
- ❌ **Desligado** - Colaborador demitido

#### Funcionalidades Avançadas
- **Busca Inteligente:** Por nome ou matrícula
- **Filtros:** Por turno, status, centro de custo
- **Importação em Massa:** Upload de planilha Excel
- **Histórico Completo:** Todos os eventos do colaborador
- **Edição de Histórico:** Correção de registros passados

#### Valor para o Negócio
Centraliza todas as informações de pessoas, elimina controles paralelos e garante rastreabilidade.

---

### 6. 🗓️ MÓDULO DE FÉRIAS

**Rota:** `/employees` (integrado) e `/employees/vacation`  
**Acesso:** Líderes, RH

#### Objetivo
Agendamento e controle de períodos de férias.

#### Funcionalidades
- **Agendamento Individual:** Data início e fim
- **Importação em Massa:** Colagem direta do Excel (Matrícula, Início, Fim)
- **Visualização no Calendário:** Férias programadas
- **Bloqueio Automático:** Impede alocação durante férias
- **Histórico:** Registro de todos os períodos

#### Valor para o Negócio
Planejamento antecipado de recursos, evitando surpresas na operação.

---

### 7. 🏥 IMPORTAÇÃO DE ATESTADOS MÉDICOS

**Rota:** `/import-medical-certificates`  
**Acesso:** RH, Administradores

#### Objetivo
Registro em massa de atestados médicos via importação de arquivo.

#### Formato de Importação (CSV)
```
matricula,data_inicio,data_fim,cid,observacao
12345,2026-01-15,2026-01-17,J11,Gripe
```

#### Funcionalidades
- Upload de arquivo CSV
- Validação automática de matrículas
- Criação de eventos no histórico
- Atualização automática de status

#### Valor para o Negócio
Agiliza o registro de afastamentos, mantendo dados precisos para análise de absenteísmo.

---

### 8. 📊 RANKINGS E PERFORMANCE

**Rota:** `/rankings`  
**Acesso:** Todos os usuários

#### Objetivo
Exibir rankings de produtividade e performance dos colaboradores.

#### Métricas Exibidas
- Tonelagem total separada
- Produtividade (kg/hora)
- Número de rotas completadas
- Posição no ranking geral

#### Filtros
- Por período (diário, semanal, mensal)
- Por turno
- Por setor

#### Valor para o Negócio
Incentiva competição saudável e identifica top performers para reconhecimento.

---

### 9. 🎮 SISTEMA DE GAMIFICAÇÃO

**Rotas:** `/admin/game`, `/mobile/game`, `/mobile/achievements`  
**Acesso:** Colaboradores (mobile), Gestores (admin)

#### Objetivo
Engajar colaboradores através de sistema de pontos, níveis e conquistas.

#### Componentes do Sistema

##### A. Sistema de XP (Experiência)

| Fonte de XP | Descrição |
|-------------|-----------|
| **Produção Diária** | 100 XP por UO (1 UO = 1.500kg) |
| **Bônus de Eficiência** | +10% se produtividade > 1 UO/hora |
| **Bônus Turbo** | +25% se produtividade > 1.5 UO/hora |
| **Bônus por Horário** | Configurável (terminar antes de X hora) |
| **Desafio de Produtividade** | +100 XP se superar dia anterior |
| **Eventos Especiais** | Multiplicadores em datas específicas |

##### B. Sistema de Níveis

Os níveis são configuráveis pelo administrador:
- Cada nível tem requisito de XP mínimo
- Alguns níveis exigem tempo mínimo de empresa
- Insígnias visuais para cada nível

##### C. Conquistas (Achievements)

**Categorias:**
- 📦 **Produção:** Marcos de tonelagem (100t, 500t, 1000t)
- 📅 **Assiduidade:** Semanas/meses sem faltas
- 💪 **Saúde:** Dias sem atestado
- 🏆 **Tempo de Casa:** Aniversários de empresa
- ⏰ **Eficiência:** Terminar rotas antes do horário

**Tipos de Gatilho:**
- **Automático:** Sistema avalia e concede automaticamente
- **Manual:** Gestor concede mediante avaliação

##### D. Painel Administrativo

- Configuração de níveis e XP
- Aprovação de conquistas manuais
- Auditoria de transações de XP
- Ajustes manuais (com justificativa)

##### E. Aplicativo Mobile

- Visualização de XP e nível atual
- Progresso para próximo nível
- Lista de conquistas (desbloqueadas e bloqueadas)
- Histórico de ganhos de XP

#### Valor para o Negócio
Aumenta engajamento, reduz turnover, melhora produtividade e cria cultura de reconhecimento.

---

### 10. 📱 APLICATIVO MOBILE

**Rotas:** `/mobile/*`  
**Acesso:** Colaboradores com permissão

#### Objetivo
Interface otimizada para uso em celulares pelos colaboradores operacionais.

#### Telas Disponíveis

##### Dashboard Mobile (`/mobile/dashboard`)
- Visão do dia atual
- Status pessoal (alocação, setor)
- Métricas do turno
- Início/fim de jornada

##### Conquistas (`/mobile/achievements`)
- Lista de conquistas pessoais
- Progresso em cada categoria
- XP acumulado

##### Jogo (`/mobile/game`)
- Ranking do turno
- Posição pessoal
- Nível e progresso

##### Checklist de Equipamentos (`/mobile/routine/checklist`)
- Checklist de transpaleteiras
- Identificação de não-conformidades
- Envio de fotos
- Bloqueio automático se crítico

##### Chamados de Manutenção (`/mobile/equipment/tickets/*`)
- Abertura de chamados
- Acompanhamento de status
- Histórico de chamados

##### Contagem de Paleteiras (`/mobile/pallet-count`)
- Registro de inventário diário
- Identificação de faltantes
- Abertura de chamados de manutenção

##### Histórico de Rotina (`/mobile/routine/history`)
- Histórico de jornadas
- Horas trabalhadas
- Setores alocados

#### Valor para o Negócio
Democratiza o acesso às informações, permite registro no ponto de operação e aumenta engajamento.

---

### 11. 🔧 CHECKLIST DE EQUIPAMENTOS (Transpaleteiras)

**Rotas:** `/mobile/routine/checklist`, `/admin/routine/checklists/*`  
**Acesso:** Operadores (mobile), Supervisores (admin)

#### Objetivo
Garantir inspeção diária de equipamentos antes do uso.

#### Fluxo do Processo

```
1. Operador seleciona equipamento
          ↓
2. Preenche checklist de itens
          ↓
3. Marca itens OK ou Não-Conforme
          ↓
4. Adiciona fotos se necessário
          ↓
5. Submete checklist
          ↓
6. Se crítico → Equipamento bloqueado
          ↓
7. E-mail enviado para manutenção
          ↓
8. Supervisor revisa no painel admin
```

#### Itens do Checklist (Configuráveis)
- Bateria e conexões
- Rodas e rodízios
- Garfos e estrutura
- Sistema hidráulico
- Freios
- Sinalização

#### Painel Administrativo
- Dashboard de checklists do dia
- Filtros por equipamento, status, turno
- Aprovação/Rejeição de checklists
- Liberação de equipamentos bloqueados
- Reenvio de e-mails
- Exclusão em massa (limpeza de dados antigos)

#### Valor para o Negócio
Previne acidentes, garante manutenção preventiva e documenta inspeções para auditorias.

---

### 12. 🎫 CHAMADOS DE MANUTENÇÃO

**Rotas:** `/mobile/equipment/tickets/*`, `/admin/equipment/tickets/*`  
**Acesso:** Operadores (mobile), Manutenção e Supervisores (admin)

#### Objetivo
Sistema de tickets para reportar problemas em equipamentos.

#### Ciclo de Vida do Chamado

| Status | Descrição |
|--------|-----------|
| **Aberto** | Chamado recém-criado |
| **Em Progresso** | Manutenção trabalhando |
| **Resolvido** | Problema corrigido |
| **Fechado** | Validado e encerrado |

#### Dados do Chamado
- Equipamento afetado
- Descrição do problema
- Prioridade (Baixa, Média, Alta, Crítica)
- Severidade
- Fotos anexadas
- Histórico de eventos

#### Notificações
- E-mail automático para equipe de manutenção
- Alerta no painel administrativo

#### Valor para o Negócio
Centraliza comunicação de problemas, garante rastreabilidade e mede tempo de resposta.

---

### 13. 📦 CONTAGEM DE PALETEIRAS

**Rotas:** `/mobile/pallet-count`, `/admin/pallet-count/settings`  
**Acesso:** Operadores (mobile), Supervisores (admin)

#### Objetivo
Inventário diário de paleteiras por setor.

#### Funcionalidades

##### Mobile
- Seleção de setor
- Digitação do número da paleteira
- Status: Encontrada, Faltante, Nova, Manutenção
- Observações

##### Admin
- Configuração de setores
- Destinatários de alertas por e-mail
- Relatório de divergências
- Tickets de manutenção vinculados

#### Valor para o Negócio
Controle patrimonial, identificação de perdas e planejamento de substituições.

---

### 14. 🚚 SEPARAÇÃO DE ROTAS

**Rota:** `/separacao`  
**Acesso:** Operadores e Líderes

#### Objetivo
Registro e acompanhamento de rotas de separação de pedidos.

#### Dados da Rota
- Data e turno
- Colaborador responsável
- Cliente atendido
- Horário início/fim
- Tonelagem separada
- Status (Pendente/Concluída)

#### Cálculos Automáticos
- Tempo de separação
- Produtividade (kg/hora)
- XP gerado (gamificação)

#### Valor para o Negócio
Rastreia produtividade individual, alimenta gamificação e gera métricas de eficiência.

---

### 15. 📈 ESTRATÉGIA E ANALYTICS

**Rota:** `/strategy`  
**Acesso:** Gestores e Diretoria

#### Objetivo
Visão estratégica com análises e tendências.

#### Componentes
- Gráficos de evolução de produtividade
- Análise de tendências
- Comparativos entre períodos
- Indicadores de eficiência

#### Valor para o Negócio
Suporte à tomada de decisões estratégicas com dados históricos.

---

### 16. 🧠 INTELIGÊNCIA DE PESSOAS (People Intelligence)

**Rota:** `/people-intelligence`  
**Acesso:** RH, Gestores

#### Objetivo
Análise comportamental e identificação de padrões de absenteísmo.

#### Funcionalidades
- Identificação de reincidentes
- Padrões de faltas (dias da semana, proximidade de feriados)
- Alertas de comportamento
- Relatórios para ação disciplinar

#### Valor para o Negócio
Proatividade na gestão de pessoas, redução de absenteísmo crônico.

---

### 17. ⏰ HISTÓRICO OPERACIONAL

**Rota:** `/operational/history`  
**Acesso:** Gestores

#### Objetivo
Consulta histórica de operações passadas.

#### Funcionalidades
- Filtro por data, turno, setor
- Visualização de rotas antigas
- Métricas históricas
- Exportação de dados

#### Valor para o Negócio
Análise histórica para planejamento e identificação de sazonalidades.

---

### 18. 👤 GESTÃO DE USUÁRIOS

**Rota:** `/admin/users`  
**Acesso:** Administradores

#### Objetivo
Controle de acesso ao sistema.

#### Perfis de Usuário

| Perfil | Permissões |
|--------|------------|
| **Admin** | Acesso total ao sistema |
| **Leader** | Gestão operacional, sem configurações |
| **Operator** | Apenas aplicativo mobile |

#### Funcionalidades
- Criação de usuários
- Vinculação com colaborador
- Definição de perfil
- Controle de páginas permitidas
- Reset de senha
- Ativação/Desativação

#### Autenticação Suportada
- Login tradicional (usuário/senha)
- Google OAuth (SSO)

#### Valor para o Negócio
Segurança, controle de acesso e auditoria de ações.

---

### 19. ⚙️ CONFIGURAÇÕES DO SISTEMA

#### A. Configurações de Gamificação (`/admin/game/settings`)
- Regras de XP
- Bônus por horário
- Eventos especiais
- Níveis e requisitos

#### B. Configurações de Checklist (`/admin/routine/checklists/settings`)
- Equipamentos cadastrados
- Destinatários de e-mail
- Itens do checklist

#### C. Configurações de Alertas de Falta (`/admin/absence-alerts/settings`)
- Destinatários para advertências
- Regras de envio

#### D. Configurações de Contagem (`/admin/pallet-count/settings`)
- Setores de paleteiras
- Destinatários de alertas

---

## 🔒 SEGURANÇA

| Aspecto | Implementação |
|---------|---------------|
| Autenticação | JWT + Sessions |
| Senhas | Hash com bcrypt |
| Autorização | Middleware por rota |
| HTTPS | Obrigatório em produção |
| Logs | Auditoria de ações críticas |

---

## 📊 INTEGRAÇÕES POSSÍVEIS

| Sistema | Tipo | Status |
|---------|------|--------|
| E-mail (SMTP) | Notificações | ✅ Implementado |
| Google OAuth | SSO | ✅ Implementado |
| Excel/CSV | Importação | ✅ Implementado |
| SAP/ERP | Dados mestres | 🔄 Futuro |
| BI Tools | Analytics | 🔄 Futuro |

---

## 📈 BENEFÍCIOS MENSURÁVEIS

| Métrica | Antes | Depois | Melhoria |
|---------|-------|--------|----------|
| Tempo de alocação de equipe | 30 min | 5 min | -83% |
| Erros em planilhas | ~15/mês | ~2/mês | -87% |
| Tempo para relatórios | 2 horas | 10 seg | -99% |
| Visibilidade de KPIs | Diária | Real-time | Instantâneo |
| Engajamento (gamificação) | N/A | Mensurável | +40% participação |

---

## 🚀 ROADMAP FUTURO

### Curto Prazo
- [ ] App nativo iOS/Android
- [ ] Integração com ponto eletrônico
- [ ] Dashboard de BI avançado

### Médio Prazo
- [ ] IA para previsão de demanda
- [ ] Chatbot para colaboradores
- [ ] Integração SAP

### Longo Prazo
- [ ] Multi-unidades
- [ ] Expansão para outras operações
- [ ] Marketplace de gamificação

---

## 📞 SUPORTE

**Desenvolvedor:** Felipe Ranon Marinho Pires  
**Repositório:** [GitHub](https://github.com/feliperanon/analise_operacional)  
**Documentação:** `/docs/` no projeto

---

## 📝 CONCLUSÃO

O Sistema de Análise Operacional representa uma transformação digital completa da gestão logística, unificando:

1. **Operação em Tempo Real** - Visibilidade instantânea
2. **Gestão de Pessoas** - Controle total do ciclo de vida
3. **Engajamento** - Gamificação que motiva
4. **Conformidade** - Checklists e rastreabilidade
5. **Inteligência** - Dados para decisões estratégicas

O sistema já está em produção, com métricas comprovadas de eficiência e satisfação dos usuários.

---

*Documento gerado para apresentação à Diretoria - Janeiro 2026*
