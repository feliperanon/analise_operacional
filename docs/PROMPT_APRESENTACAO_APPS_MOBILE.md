# Prompt para Criar Apresentação: Apps Mobile - Portal do Colaborador

Use este documento como base para que uma IA gere uma apresentação (slides) descrevendo o funcionamento dos aplicativos mobile do sistema, incluindo fluxos de entregas, ações do motorista, histórico de entregas e chamados de equipamento.

---

## 1. Contexto Geral

O sistema possui uma interface mobile (responsiva) acessada por colaboradores para:
- **Rotas de entregas** – motoristas e ajudantes acompanham e registram entregas em campo
- **Histórico de entregas** – consulta de entregas por período (motoristas e ajudantes)
- **Chamados de equipamento** – abertura de chamados de manutenção para transpaleteiras/equipamentos
- **Dashboard de devoluções** – acompanhamento de taxa de devolução (avaliação)

Acesso via URLs como `http://127.0.0.1:8000/mobile/delivery`, `/mobile/entregas`, `/mobile/equipment/tickets/new`, etc.

---

## 2. Fluxo de Ações na Rota de Entregas (Iniciar, Finalizar, Devolução, Reabrir)

### 2.1 Pré-requisitos

- Colaborador logado no mobile
- Rotas planejadas para o dia (com cliente, peso, valor, endereço)
- Sessão de entrega aberta (motorista iniciou com placa, KM de saída e opcionalmente ajudantes)

### 2.2 Estados de uma Parada (Route)

| Estado | Descrição |
|--------|-----------|
| **pendente** | Cliente ainda não visitado |
| **iniciada** | Entrega em andamento no endereço |
| **entregue** | Entrega concluída com sucesso |
| **devolucao** | Devolução registrada (total ou parcial) |
| **reaberta** | Parada foi entregue/devolvida e reaberta para nova tentativa |

### 2.3 Ações e como funcionam

#### **Iniciar** (botão "Iniciar" nos cards pendentes)

- **Onde:** Nos cards de "Próximas Entregas" – cada parada pendente ou reaberta tem botão "Iniciar"
- **Condições:** Não pode haver outra entrega iniciada ao mesmo tempo
- **Efeito:**
  - Status da rota: `pendente` → `iniciada`
  - Registra horário de início (`delivery_started_at`)
  - O card passa para o bloco "Em Andamento" no topo da tela
- **Regra:** Só pode ter uma entrega iniciada por vez

#### **Finalizar** (botão "Finalizar" na entrega em andamento)

- **Onde:** No card azul "Em Andamento" – botão verde "Finalizar"
- **Condições:** A rota precisa estar com status `iniciada`
- **Efeito:**
  - Status: `iniciada` → `entregue`
  - Registra horário de fim (`delivery_finished_at`)
  - O card sai de "Em Andamento" e vai para o bloco "Entregues"
  - Rota considerada concluída com sucesso

#### **Devolução** (botão "Devolução" na entrega em andamento)

- **Onde:** No card "Em Andamento" – botão amarelo "Devolução"
- **Condições:** Rota deve estar `iniciada`
- **Fluxo:**
  1. Abre modal "Registrar Devolução"
  2. Obrigatório escolher **motivo** (lista padrão: Cliente ausente, Endereço incorreto, Recusado, etc.)
  3. Opcional marcar "Devolução parcial" e informar peso e valor parcial
  4. Ao confirmar:
     - Status: `iniciada` → `devolucao`
     - Registra horário de devolução
     - Armazena motivo, peso e valor devolvidos
     - O card vai para o bloco "Devoluções"

#### **Reabrir** (botão "Reabrir" nas entregues ou devolvidas)

- **Onde:** Nos acordeões "Entregues" e "Devoluções" – cada card tem botão "Reabrir"
- **Condições:**
  - Rota deve estar `entregue` ou `devolucao`
  - Não pode haver outra entrega iniciada
- **Efeito:**
  - Status: `entregue`/`devolucao` → `reaberta`
  - A parada volta para "Próximas Entregas"
  - Incrementa contador de reaberturas
  - Permite nova tentativa (iniciar novamente)

### 2.4 Sequência típica

1. Motorista vê lista de paradas pendentes
2. Clica em **Iniciar** na primeira parada → card vai para "Em Andamento"
3. No endereço:
   - Se entregou com sucesso → **Finalizar**
   - Se devolveu → **Devolução** (modal com motivo)
4. Se precisar refazer uma parada já concluída → **Reabrir** no card correspondente
5. Ao terminar todas as paradas → botão fixo **Encerrar Rota** (KM de chegada)

---

## 3. Histórico de Entregas (`/mobile/entregas`)

### 3.1 Propósito

Tela para motoristas e ajudantes consultarem o histórico de entregas em um período, com indicadores por dia.

### 3.2 Funcionamento

- **Filtro:** Data inicial e data final (padrão: últimos 30 dias)
- **Fonte de dados:** API `/api/mobile/delivery/history?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`
- **Conteúdo:** Dias com entregas, cada dia mostrando:
  - Data, placa do caminhão
  - Motorista e ajudantes (da sessão do dia)
  - Taxa de devolução do dia (%)
  - Quantidade de clientes entregues, devolvidos e total
  - Horário início, fim e tempo de percurso

### 3.3 Permissões

Acesso liberado para:
- `mobile_access_separation` (App Separação)
- `mobile_access_admin_start` (Líder / Abertura manual)
- `mobile_access_helper` (Pode ser Ajudante)

### 3.4 Comportamento para Ajudantes

- Ajudantes veem dias em que participaram como helper (rotas do motorista ou rotas onde foram ajudantes)
- Métricas incluem rotas onde foram ajudantes

---

## 4. Abrir Chamado de Equipamento (`/mobile/equipment/tickets/new`)

### 4.1 Propósito

Registrar falha ou problema em equipamento (ex.: transpaleteira) para acionar manutenção.

### 4.2 Funcionamento

- **Entrada:** Formulário com:
  - **Equipamento:** select com lista de TranspalletEquipment (código + status disponível/bloqueado)
  - **Descrição do problema:** campo obrigatório (ex.: "Rodas travando, alavanca com folga")
  - **Fotos (opcional):** upload de imagens (JPG, PNG, WEBP, máx. 15MB por imagem)
- **Envio:** POST para `/api/equipment/tickets`
- **Regras:**
  - Equipamento e descrição obrigatórios
  - Palavras-chave críticas (freio, vazamento, bateria, travado etc.) ou fotos anexadas → prioridade/severidade alta
  - Pode verificar se já existe chamado aberto no mesmo dia (aviso, não bloqueia)

### 4.3 Fluxo pós-submissão

1. Chamado é criado (status `open`)
2. E-mail é enviado aos responsáveis pela manutenção (se configurado)
3. Redirecionamento para o dashboard com mensagem de sucesso
4. Admin/líder pode ver e resolver chamados em `/admin/equipment/tickets`

### 4.4 Permissões

- Requer `mobile_access_checklist` (App Checklist Operacional)
- Lista de chamados abertos dos últimos 3 dias aparece na tela para contexto

---

## 5. Dashboard de Devoluções (`/mobile/returns`)

### 5.1 Propósito

Colaborador avaliar sua própria taxa de devolução em relação à meta (ex.: 2% dos valores).

### 5.2 Funcionamento

- Filtro por período (mês/ano)
- API: `/api/mobile/returns-data`
- Exibe:
  - Total em R$ devolvido
  - Percentual de devolução
  - Gráfico de evolução
  - Detalhamento por cliente

### 5.3 Permissões

- `mobile_access_returns`
- Ou `mobile_access_separation` ou `mobile_access_admin_start`

---

## 6. Rota de Entregas – Visão Geral da Tela

### 6.1 Componentes principais

- **Header:** Título "Rota de Entregas", botão voltar, botão atualizar
- **Card Rota Ativa** (quando sessão aberta):
  - Motorista, ajudantes, placa, KM, horário de início
  - Chips: Total, Pendentes, Aberta, Entregues, Devoluções
  - Alerta de devoluções do mês (se acima da meta)
- **Em Andamento:** Card destacado com parada atual e botões Finalizar / Devolução
- **Próximas Entregas:** Cards pendentes/reabertas com botão Iniciar, link Google Maps, chips (peso, valor, status)
- **Entregues / Devoluções:** Acordeões com cards e botão Reabrir
- **Botão Encerrar Rota:** Fixo no rodapé (só motorista)

### 6.2 Modo Ajudante

- Ajudantes veem a mesma tela em modo somente leitura
- Painel "Rota Ativa" com dados do motorista e ajudantes
- Sem botões: Iniciar, Finalizar, Devolução, Reabrir, Editar, Encerrar Rota

---

## 7. URLs e Acesso

| URL | Descrição |
|-----|-----------|
| `/mobile/delivery` | Rota de entregas (execução) |
| `/mobile/entregas` | Histórico de entregas |
| `/mobile/equipment/tickets` | Lista de chamados |
| `/mobile/equipment/tickets/new` | Novo chamado de equipamento |
| `/mobile/returns` | Dashboard de devoluções |

---

## 8. Instruções para a IA Geradora da Apresentação

Com base neste documento:

1. **Estruture os slides** em seções lógicas: Contexto → Rotas → Histórico → Chamados → Devoluções.
2. **Use fluxogramas ou diagramas** para: Iniciar → Finalizar/Devolução → Reabrir.
3. **Inclua tabelas** para estados da parada e permissões por módulo.
4. **Mostre capturas ou wireframes** conceituais das telas principais, se disponíveis.
5. **Destaque as regras de negócio:** uma entrega iniciada por vez, motivo obrigatório em devolução, reabertura permitida.
6. **Inclua slide de permissões** (mobile_access_*) e quem acessa cada módulo.
7. **Foque na experiência do motorista e do ajudante** – o que cada um vê e faz.

---

*Documento gerado para suporte à criação de apresentação sobre os apps mobile do Portal do Colaborador.*
