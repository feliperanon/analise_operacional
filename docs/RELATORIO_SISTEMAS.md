# Relatório de Sistemas Operacionais

**Data:** 29/01/2026  
**Versão:** 1.0  
**Autor:** Sistema de Gestão Operacional

---

## 1. Organograma Operacional

### 1.1 Visão Geral

O **Organograma Operacional** é um módulo do sistema que permite visualizar a estrutura completa de alocação de colaboradores por setor e turno. Ele fornece uma visão em tempo real de como a equipe está distribuída na operação.

### 1.2 Acesso

- **URL:** `/smart-flow/organogram`
- **Permissões:** Líderes e Administradores
- **Menu:** Smart Flow → Organograma

### 1.3 Funcionalidades

#### 1.3.1 Visualização de Setores

O organograma exibe todos os setores cadastrados com:

| Informação | Descrição |
|------------|-----------|
| **Nome do Setor** | Identificação do setor (ex: Recebimento, Expedição) |
| **Sub-setores** | Áreas dentro do setor (ex: Descarga, Conferência) |
| **Meta** | Número ideal de colaboradores |
| **Alocados** | Número atual de colaboradores alocados |
| **Vagas** | Posições em aberto (Meta - Alocados) |
| **% Ocupação** | Percentual de preenchimento |

#### 1.3.2 KPIs do Header

No topo da página são exibidos indicadores gerais:

- **Total Setores:** Quantidade de setores na operação
- **Sub-setores:** Quantidade total de sub-setores
- **Alocados:** Total de colaboradores alocados
- **Meta Total:** Soma das metas de todos setores
- **Vagas Abertas:** Total de posições não preenchidas
- **% Ocupação:** Percentual geral de ocupação
- **Gerado em:** Data/hora da geração do relatório

#### 1.3.3 Detalhes dos Colaboradores

Cada colaborador é exibido com:
- Iniciais (avatar)
- Nome completo
- Cargo/função
- Indicador de status (verde = ativo)

#### 1.3.4 Vagas em Aberto

Posições não preenchidas são destacadas com:
- Borda amarela tracejada
- Ícone de alerta
- Texto "VAGA EM ABERTO"

### 1.4 Impressão

O sistema possui funcionalidade de impressão otimizada:

#### Recursos de Impressão:
1. **Pré-visualização:** Botão "Pré-visualizar Impressão" mostra como ficará no papel
2. **Escala Automática:** Setores com mais colaboradores têm fonte menor automaticamente
3. **1 Setor por Página:** Cada setor é impresso em página separada
4. **Quebra de Página:** Indicador visual de onde a página será dividida

#### Configurações Recomendadas:
- **Orientação:** Paisagem
- **Margens:** Mínimas (6mm)
- **Gráficos de segundo plano:** ✅ Habilitado (obrigatório para cores)

#### Tabela de Escala Automática:

| Colaboradores | Tamanho Fonte | Colunas |
|---------------|---------------|---------|
| Até 15 | 8pt | 3 |
| Até 25 | 7pt | 3 |
| Até 40 | 6.5pt | 4 |
| Até 60 | 6pt | 4 |
| Até 80 | 5.5pt | 5 |
| 80+ | 5pt | 6 |

### 1.5 Fluxo de Dados

```
Smart Flow (Alocações) → Banco de Dados → Organograma (Visualização)
```

O organograma busca as alocações do dia/turno selecionado e agrupa por setor/sub-setor.

---

## 2. Sistema de Contagem de Paleteiras

### 2.1 Visão Geral

O **Sistema de Contagem de Paleteiras** permite rastrear e controlar as paleteiras (transpaleteiras) da operação, comparando a contagem diária com o dia anterior para identificar equipamentos faltantes ou novos.

### 2.2 Acesso

#### Administração (Configurações):
- **URL:** `/admin/pallet-count/settings`
- **Menu:** Administração → Contagem de Paleteiras
- **Permissões:** Administradores e usuários com `checklist_admin`

#### Mobile (Contagem Diária):
- **URL:** `/mobile/pallet-count`
- **Menu:** Dashboard Mobile → Contagem de Paleteiras
- **Permissões:** Colaboradores autenticados

### 2.3 Módulo Administrativo

#### 2.3.1 Gestão de Setores

Cadastro de setores onde as paleteiras ficam alocadas:

| Campo | Descrição |
|-------|-----------|
| **Nome** | Nome do setor (ex: Expedição, Recebimento) |
| **Descrição** | Descrição opcional |
| **Ordem** | Ordem de exibição |
| **Ativo** | Se o setor está ativo |

#### 2.3.2 Chamados de Manutenção

Registro de paleteiras enviadas para manutenção:

| Campo | Descrição |
|-------|-----------|
| **Número da Paleteira** | Identificação do equipamento |
| **Setor** | Setor de origem |
| **Tipo de Problema** | bateria, rodas, garfo, motor, outro |
| **Descrição** | Detalhes do problema |
| **Prioridade** | baixa, média, alta, urgente |
| **Status** | aberto, em_andamento, concluído, cancelado |
| **Imagens** | Fotos do problema |

#### 2.3.3 Retorno de Manutenção

Quando uma paleteira volta da manutenção:
- Registra número da paleteira retornada (pode ser diferente)
- Data de retorno
- Observações

#### 2.3.4 E-mails de Alerta

Cadastro de destinatários para alertas automáticos:

| Campo | Descrição |
|-------|-----------|
| **E-mail** | Endereço de e-mail |
| **Nome** | Nome do destinatário |
| **Tipo de Alerta** | todos, faltante, manutenção |
| **Ativo** | Se está ativo |

### 2.4 Módulo Mobile (Contagem)

#### 2.4.1 Interface de Contagem

A tela mobile exibe:

**Header:**
- Data atual
- Turno atual
- Total contadas

**Estatísticas:**
- Esperadas (do dia anterior)
- Contadas (registradas hoje)
- Faltando (esperadas não encontradas)
- Novas (não existiam ontem)

**Input Rápido:**
- Campo para digitar número da paleteira
- Botão de confirmação

**Filtro por Setor:**
- Botões para filtrar por setor
- "Todos" mostra todas

#### 2.4.2 Abas de Visualização

| Aba | Conteúdo |
|-----|----------|
| **Esperadas** | Paleteiras do dia anterior que devem ser encontradas |
| **Novas** | Paleteiras registradas hoje que não existiam ontem |
| **Manutenção** | Paleteiras com chamado de manutenção aberto |

#### 2.4.3 Fluxo de Contagem

```
1. Colaborador acessa /mobile/pallet-count
2. Sistema carrega paleteiras do dia anterior (esperadas)
3. Colaborador digita número da paleteira
4. Sistema verifica:
   - Se está nas esperadas → marca como "encontrada"
   - Se não está → registra como "nova"
5. Ao finalizar, sistema identifica faltantes
6. Alertas são enviados se configurado
```

#### 2.4.4 Status das Paleteiras

| Status | Descrição |
|--------|-----------|
| **found** | Encontrada na contagem |
| **missing** | Não foi encontrada (estava ontem) |
| **new** | Nova (não existia ontem) |
| **maintenance** | Em manutenção |

### 2.5 Modelo de Dados

#### Tabela: `palletsector`
```sql
- id (PK)
- name (VARCHAR)
- description (TEXT)
- is_active (BOOLEAN)
- order (INTEGER)
- created_at (TIMESTAMP)
```

#### Tabela: `palletcount`
```sql
- id (PK)
- pallet_number (VARCHAR) -- Número da paleteira
- date (VARCHAR) -- YYYY-MM-DD
- shift (VARCHAR) -- Manhã, Tarde, Noite
- sector_id (INTEGER, FK)
- employee_id (INTEGER, FK)
- status (VARCHAR) -- found, missing, new, maintenance
- observations (TEXT)
- created_at (TIMESTAMP)
```

#### Tabela: `palletmaintenanceticket`
```sql
- id (PK)
- pallet_number (VARCHAR)
- sector_id (INTEGER, FK)
- employee_id (INTEGER, FK)
- issue_type (VARCHAR)
- description (TEXT)
- priority (VARCHAR)
- images (JSON)
- status (VARCHAR)
- returned_pallet_number (VARCHAR)
- return_date (TIMESTAMP)
- return_notes (TEXT)
- email_sent_at (TIMESTAMP)
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)
```

#### Tabela: `palletcountemailrecipient`
```sql
- id (PK)
- email (VARCHAR)
- name (VARCHAR)
- alert_type (VARCHAR) -- all, missing, maintenance
- is_active (BOOLEAN)
- created_at (TIMESTAMP)
```

### 2.6 Relatórios e Alertas

#### Alertas Automáticos:
- **Paleteira Faltante:** Enviado quando uma paleteira não é encontrada
- **Manutenção:** Enviado quando um chamado é aberto
- **Retorno:** Enviado quando uma paleteira volta da manutenção

#### Informações do Alerta:
- Número da paleteira
- Setor
- Data/hora
- Responsável pela contagem
- Histórico recente

---

## 3. Integração entre Sistemas

### 3.1 Smart Flow + Organograma

O Organograma é gerado a partir das alocações feitas no Smart Flow:

```
Smart Flow → Salva Alocações → Organograma lê e exibe
```

### 3.2 Checklist de Paleteiras + Manutenção

O sistema de contagem integra com o módulo de manutenção:

```
Contagem → Identifica Problema → Abre Chamado → Notifica Manutenção
```

---

## 4. Permissões

| Funcionalidade | Admin | Leader | Checklist Admin | Colaborador |
|----------------|-------|--------|-----------------|-------------|
| Ver Organograma | ✅ | ✅ | ❌ | ❌ |
| Imprimir Organograma | ✅ | ✅ | ❌ | ❌ |
| Config. Paleteiras | ✅ | ❌ | ✅ | ❌ |
| Contagem Mobile | ✅ | ✅ | ✅ | ✅ |
| Abrir Chamado | ✅ | ✅ | ✅ | ✅ |

---

## 5. Roadmap Futuro

### Organograma:
- [ ] Exportar para Excel
- [ ] Histórico de alocações
- [ ] Comparativo entre turnos

### Contagem de Paleteiras:
- [ ] Leitura por código de barras/QR Code
- [ ] Dashboard com gráficos de tendência
- [ ] Integração com sistema de manutenção externo
- [ ] App offline com sincronização

---

## 6. Suporte

Para dúvidas ou problemas:
- **E-mail:** suporte@empresa.com
- **Sistema:** Menu Ajuda → Suporte

---

*Documento gerado automaticamente pelo Sistema de Gestão Operacional*
