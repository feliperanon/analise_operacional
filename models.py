from datetime import datetime, time
from typing import Optional, List
from pydantic import field_validator
from sqlmodel import Field, SQLModel, Relationship

class Shift(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: datetime = Field(default_factory=datetime.now)
    start_time: time = Field(default_factory=lambda: datetime.now().time())
    end_time: Optional[time] = None
    headcount: int = Field(default=0)
    tonnage: float = Field(default=0.0)
    status: str = Field(default="open") # open, closed
    ai_summary: Optional[str] = None
    
    events: List["Event"] = Relationship(back_populates="shift")

class HeadcountTarget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shift_name: str = Field(index=True) # Manhã, Tarde, Noite
    target_value: int

class Employee(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    registration_id: str = Field(index=True, unique=True) # Matrícula
    seller_code: Optional[str] = Field(default=None, index=True) # Código do vendedor
    name: str

    @field_validator("name", mode="before")
    @classmethod
    def name_uppercase(cls, v: str) -> str:
        if isinstance(v, str):
            return (v or "").strip().upper()
        return v

    admission_date: Optional[datetime] = None
    cost_center: Optional[str] = None
    role: str # Cargo
    birthday: Optional[datetime] = None
    photo_url: Optional[str] = None
    phone: Optional[str] = None  # Telefone BR: DDD + número (ex: 31994097893)
    
    # Status
    # active, vacation, away, fired, day_off
    status: str = Field(default="active")
    work_shift: str = Field(default="Manhã") # Manhã, Tarde, Noite
    
    # Work Days (dias da semana que trabalha)
    work_days: Optional[str] = Field(default='["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]')

    # Schedule (Horário de Trabalho) e.g. "07:00 - 15:20"
    work_schedule: Optional[str] = Field(default=None)
    
    # Access Control
    mobile_access: bool = Field(default=False)
    mobile_access_separation: bool = Field(default=False)
    mobile_access_checklist: bool = Field(default=False)
    mobile_access_admin_start: bool = Field(default=False) # Permissão para líder abrir rota manualmente
    mobile_access_returns: bool = Field(default=False) # Dashboard de devoluções (avaliação do colaborador)
    mobile_access_helper: bool = Field(default=False)  # Pode ser selecionado como ajudante nas rotas
    mobile_access_gatehouse: bool = Field(default=False)  # Módulo Portaria
    mobile_access_escala: bool = Field(default=False)  # Módulo Escala operacional (web)
    
    # Gamification
    total_xp: float = Field(default=0.0) # Accumulated Tonnage/Score
    
    # Vacation Scheduling
    vacation_start: Optional[datetime] = None
    vacation_end: Optional[datetime] = None
    
    # Termination
    termination_date: Optional[datetime] = None
    
    # Replacement tracking
    replaced_by: Optional[int] = Field(default=None, foreign_key="employee.id")  # ID do colaborador que substituiu este




    events: List["Event"] = Relationship(back_populates="employee")

from sqlalchemy import Column, JSON, UniqueConstraint
from datetime import datetime

class DailyOperation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True) # YYYY-MM-DD
    shift: str = Field(index=True) # Manhã, Tarde, Noite
    
    # Metrics
    tonnage: int = Field(default=0)
    attendance_log: Optional[dict] = Field(default={}, sa_column=Column(JSON))
    logs: Optional[List[dict]] = Field(default=[], sa_column=Column(JSON)) # Store snapshots/events history
    
    # Logistics
    arrival_time: Optional[str] = Field(default=None)
    exit_time: Optional[str] = Field(default=None)
    
    # Closing
    report: Optional[str] = Field(default=None)
    rating: int = Field(default=0)
    status: str = Field(default="open") # open, closed
    
    # Meta
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    text: str
    type: str # erro, alerta, ideia, ocorrencia, falta, atestado, advertencia
    category: str # infraestrutura, pessoas, processo, fornecedor
    sector: str = Field(default="Geral") # selecao, expedicao, camara
    impact: str = Field(default="low") # low, medium, high
    reference_type: Optional[str] = Field(default=None, index=True)
    reference_id: Optional[int] = Field(default=None, index=True)
    
    shift_id: Optional[int] = Field(default=None, foreign_key="shift.id")
    shift: Optional[Shift] = Relationship(back_populates="events")

    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    employee: Optional[Employee] = Relationship(back_populates="events")

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)  # Email/username
    password_hash: Optional[str] = None
    role: str = Field(default="leader")
    is_active: bool = Field(default=True)
    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    allowed_pages: Optional[str] = Field(default="[]")
    google_sub: Optional[str] = Field(default=None, index=True)
    reset_token_hash: Optional[str] = None
    reset_token_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class SectorConfiguration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shift_name: str = Field(index=True) # Manhã, Tarde, Noite
    config_json: dict = Field(default={}, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=datetime.now)

class CargoMaster(SQLModel, table=True):
    """Cadastro mestre de funções/cargos com salário e descrição."""
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)  # Nome padrão do cargo (maiúsculas, completo)
    salario_base: Optional[float] = Field(default=None)  # Salário base
    descricao: Optional[str] = Field(default=None)  # Descrição da função
    status: str = Field(default="ATIVO", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ClientGroup(SQLModel, table=True):
    """Agrupa vários cadastros de cliente (rede, bandeira) para análise consolidada nos BIs."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.now)


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)  # Nome principal (Razão Social ou Nome Fantasia)
    client_group_id: Optional[int] = Field(default=None, foreign_key="clientgroup.id", index=True)
    # Campos de cadastro completo
    nb: Optional[str] = Field(default=None, index=True)  # Número/código do cliente
    vendedor_id: Optional[int] = Field(default=None, foreign_key="employee.id", index=True)
    setor: Optional[str] = Field(default=None, index=True)  # espelha seller_code do vendedor (legado / BI)
    me: Optional[str] = Field(default=None)
    sa: Optional[str] = Field(default=None)
    visita: Optional[str] = Field(default=None)
    nome_fantasia: Optional[str] = Field(default=None, index=True)  # FANTAS
    razao_social: Optional[str] = Field(default=None, index=True)
    cnpj_cpf: Optional[str] = Field(default=None, index=True)
    municipio: Optional[str] = Field(default=None, index=True)
    bairro: Optional[str] = Field(default=None)
    endereco: Optional[str] = Field(default=None)
    fone: Optional[str] = Field(default=None)
    fone_e164: Optional[str] = Field(default=None, index=True)  # E.164 para dedup
    endereco_normalizado: Optional[str] = Field(default=None, index=True)  # Endereço higienizado para dedup
    segmento: Optional[str] = Field(default=None, index=True)
    status_cliente: Optional[str] = Field(default=None, index=True)  # STATUS (ativo, inativo, etc.)
    # Cadastro Mestre Logístico
    status_operacional: Optional[str] = Field(default="ATIVO", index=True)  # ATIVO, FECHOU, INATIVO, EM_VALIDACAO
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    complemento: Optional[str] = None
    referencia: Optional[str] = None
    observacoes_acesso: Optional[str] = None  # entrada lateral, doca, etc.
    fone_alternativo: Optional[str] = None
    observacoes_contato: Optional[str] = None
    janela_dias_semana: Optional[str] = None  # JSON: ["seg","ter",...]
    janela_horario_inicio: Optional[str] = None  # HH:MM
    janela_horario_fim: Optional[str] = None  # HH:MM
    prioridade_logistica: Optional[str] = Field(default=None, index=True)  # A, B, C
    lgpd_nao_contatar: bool = Field(default=False)
    lgpd_restricao_dados: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None

    # Geolocalização
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    geocoding_status: Optional[str] = Field(default="pending", index=True)  # pending, success, failed
    geocoded_at: Optional[datetime] = Field(default=None)
    geocoding_source: Optional[str] = Field(default=None)
    geocoding_error: Optional[str] = Field(default=None)
    address_normalized: Optional[str] = Field(default=None)

    def get_full_address(self) -> str:
        """Retorna endereço completo formatado para geocodificação."""
        parts = []
        logradouro = self.logradouro or self.endereco
        if logradouro:
            parts.append(logradouro)
        if self.numero:
            parts.append(self.numero)
        if self.bairro:
            parts.append(self.bairro)
        if self.municipio:
            parts.append(self.municipio)
        return ", ".join(p for p in parts if p)

    def has_valid_coordinates(self) -> bool:
        """Verifica se o cliente possui coordenadas geográficas válidas."""
        return (
            self.latitude is not None
            and self.longitude is not None
            and -90.0 <= self.latitude <= 90.0
            and -180.0 <= self.longitude <= 180.0
        )


class ClientAuditLog(SQLModel, table=True):
    """Histórico de alterações do cadastro de cliente."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    changed_by: Optional[str] = None  # username
    changed_at: datetime = Field(default_factory=datetime.now, index=True)
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    action: str = Field(default="update", index=True)  # update, create, delete


class ClientImportBatch(SQLModel, table=True):
    """Lote de importação de clientes (para resolução de conflitos)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    filename: Optional[str] = None
    status: str = Field(default="pending", index=True)  # pending, completed
    created_by: Optional[str] = None  # username
    log_created: int = Field(default=0)
    log_updated: int = Field(default=0)
    log_merged: int = Field(default=0)
    log_skipped: int = Field(default=0)
    log_rejected: int = Field(default=0)


class ClientImportStaging(SQLModel, table=True):
    """Linha de importação (para resolução de conflitos)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="clientimportbatch.id", index=True)
    row_index: int = Field(index=True)
    # Dados normalizados (JSON)
    name: str
    nb: Optional[str] = None
    setor: Optional[str] = None
    me: Optional[str] = None
    sa: Optional[str] = None
    visita: Optional[str] = None
    nome_fantasia: Optional[str] = None
    razao_social: Optional[str] = None
    cnpj_cpf: Optional[str] = None
    municipio: Optional[str] = None
    bairro: Optional[str] = None
    endereco: Optional[str] = None
    endereco_normalizado: Optional[str] = None
    fone: Optional[str] = None
    fone_e164: Optional[str] = None
    segmento: Optional[str] = None
    status_cliente: Optional[str] = None
    municipio_key: Optional[str] = None
    bairro_key: Optional[str] = None
    # Conflito
    conflict_type: Optional[str] = None  # fone, razao_bairro, endereco
    conflict_client_id: Optional[int] = Field(default=None, foreign_key="client.id")
    action: str = Field(default="pending", index=True)  # pending, create, merge, skip


# --- Frota / Veículos ---
class Vehicle(SQLModel, table=True):
    """Cadastro de veículos (caminhões, motos, carros) para checklist, manutenção e histórico de motoristas."""
    id: Optional[int] = Field(default=None, primary_key=True)
    placa: str = Field(index=True, unique=True)
    vehicle_type: str = Field(index=True)  # caminhao, moto, carro
    marca: str = Field(index=True)
    modelo: str
    renavam: Optional[str] = None
    ano: Optional[str] = None  # Ex: "2019/2019", "2021/2022"
    crv_number: Optional[str] = None  # Nº do CRV (Certificado de Registro de Veículo)
    chassi: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    in_workshop: bool = Field(default=False, index=True)  # Está na oficina
    sale_value: Optional[float] = None  # Valor da venda (quando vendido)
    sold_at: Optional[datetime] = None  # Data da venda
    odometer_km: Optional[float] = Field(default=None, index=True)  # Último KM (atualizado pelo checklist ou edição)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class WorkshopServiceOrder(SQLModel, table=True):
    """OS da oficina, com origem manual/checklist/preventiva e plano de ação obrigatório."""
    id: Optional[int] = Field(default=None, primary_key=True)
    vehicle_id: Optional[int] = Field(default=None, foreign_key="vehicle.id", index=True)
    checklist_id: Optional[int] = Field(default=None, foreign_key="transpalletchecklist.id", index=True)
    driver_employee_id: Optional[int] = Field(default=None, foreign_key="employee.id", index=True)
    origin: str = Field(default="manual", index=True)  # manual | checklist | preventiva
    order_type: str = Field(default="corretiva", index=True)  # corretiva | preventiva
    priority: str = Field(default="medium", index=True)  # low | medium | high | critical
    status: str = Field(default="open", index=True)  # open | triage | in_progress | waiting_parts | done | closed
    title: str = Field(default="Ordem de serviço")
    problem_description: str = Field(default="")
    preventive_note: Optional[str] = None
    due_date: Optional[datetime] = None
    responsible_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    origin_type: Optional[str] = Field(default=None, index=True)
    problem_category: Optional[str] = Field(default=None, index=True)
    operational_impact: Optional[str] = Field(default=None, index=True)
    vehicle_block_status: str = Field(default="none", index=True)  # none | preventive | critical
    vehicle_block_reason: Optional[str] = None
    vehicle_blocked_at: Optional[datetime] = None
    vehicle_blocked_by: Optional[str] = None
    vehicle_released_at: Optional[datetime] = None
    vehicle_released_by: Optional[str] = None
    external_supplier_required: bool = Field(default=False, index=True)
    supplier_name: Optional[str] = None
    supplier_contact: Optional[str] = None
    supplier_service_type: Optional[str] = None
    supplier_sent_at: Optional[datetime] = None
    supplier_expected_return_at: Optional[datetime] = None
    supplier_status: str = Field(default="not_sent", index=True)  # not_sent | sent | waiting_quote | quote_received | approved | in_service | finalized | canceled
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    final_amount: Optional[float] = None
    parts_cost: Optional[float] = None
    labor_cost: Optional[float] = None
    third_party_cost: Optional[float] = None
    total_cost: Optional[float] = None
    invoice_number: Optional[str] = None
    warranty_notes: Optional[str] = None
    odometer_km: Optional[float] = Field(default=None, index=True)
    latest_pdf_path: Optional[str] = None
    latest_pdf_generated_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    closed_at: Optional[datetime] = None
    issue_count: int = Field(default=0)
    action_plan_json: List[dict] = Field(default=[], sa_column=Column(JSON))
    opened_by: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now, index=True)


class WorkshopServiceOrderEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    service_order_id: int = Field(foreign_key="workshopserviceorder.id", index=True)
    vehicle_id: Optional[int] = Field(default=None, foreign_key="vehicle.id", index=True)
    event_type: str = Field(index=True)
    event_title: str
    event_description: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    created_by: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)


class WorkshopServiceOrderAttachment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    service_order_id: int = Field(foreign_key="workshopserviceorder.id", index=True)
    vehicle_id: Optional[int] = Field(default=None, foreign_key="vehicle.id", index=True)
    attachment_type: str = Field(default="other", index=True)
    file_name: str
    file_path: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_by: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)


class Route(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True) # YYYY-MM-DD
    shift: str = Field(default="Manhã", index=True) # Manhã, Tarde, Noite
    employee_id: int = Field(foreign_key="employee.id")
    client_id: int = Field(foreign_key="client.id")
    start_time: str # HH:MM
    end_time: Optional[str] = None # HH:MM
    tonnage: float = 0.0
    type: str = Field(default="separation", index=True)  # separation, delivery
    valor_financeiro: Optional[float] = None  # R$ mercadoria
    devolucao_volume: Optional[float] = None  # volume devolvido (ton)
    valor_devolucao: Optional[float] = None  # R$ valor da devolução
    delivery_status: Optional[str] = Field(default=None, index=True)  # pendente, iniciada, cancelada, devolucao, entregue
    delivery_route_code: Optional[str] = Field(default=None, index=True)
    delivery_order_number: Optional[str] = Field(default=None, index=True)
    delivery_client_code: Optional[str] = Field(default=None, index=True)
    delivery_vehicle_plate: Optional[str] = Field(default=None, index=True)
    delivery_cep: Optional[str] = None
    delivery_address: Optional[str] = None
    delivery_neighborhood: Optional[str] = Field(default=None, index=True)
    delivery_city: Optional[str] = Field(default=None, index=True)
    delivery_state: Optional[str] = Field(default=None, index=True)
    delivery_type: Optional[str] = Field(default=None, index=True)
    delivery_total_weight: Optional[float] = None
    delivery_order_date: Optional[str] = Field(default=None, index=True)  # YYYY-MM-DD
    delivery_source_file: Optional[str] = None
    delivery_return_category: Optional[str] = Field(default=None, index=True)
    delivery_return_reason: Optional[str] = None
    delivery_return_photo_url: Optional[str] = None  # URL da foto do estabelecimento fechado
    delivery_notified_commercial: Optional[bool] = None
    delivery_notified_commercial_name: Optional[str] = None
    delivery_notified_logistics: Optional[bool] = None
    delivery_notified_logistics_name: Optional[str] = None
    delivery_started_at: Optional[str] = None   # HH:MM ou ISO (DB legada VARCHAR ampliada no startup)
    delivery_finished_at: Optional[str] = None  # HH:MM ou ISO
    delivery_canceled_at: Optional[str] = None  # HH:MM ou ISO
    delivery_returned_at: Optional[str] = None  # HH:MM ou datetime ISO (mobile/auto-close)
    delivery_time_log: Optional[str] = None  # JSON array com histórico de status/horários
    delivery_reopen_count: Optional[int] = 0
    delivery_helpers_json: Optional[str] = None  # JSON list de employee_id (ajudantes)
    delivery_whatsapp_status: Optional[str] = Field(default=None, index=True)
    delivery_whatsapp_ready_at: Optional[datetime] = Field(default=None, index=True)
    delivery_whatsapp_last_sent_at: Optional[datetime] = Field(default=None, index=True)
    delivery_whatsapp_last_sent_by: Optional[str] = Field(default=None, index=True)
    delivery_whatsapp_summary_json: Optional[str] = None
    # Coordenadas GPS do motorista no momento da ação (capturadas pelo app mobile)
    driver_lat_start: Optional[float] = None   # ao iniciar entrega
    driver_lon_start: Optional[float] = None
    driver_lat_end: Optional[float] = None    # ao finalizar (entregue) ou devolver
    driver_lon_end: Optional[float] = None
    status: str = "pending" # pending, completed
    # Módulo Escala: nao_escalado | escalado | em_ajuste | pendencia
    escala_status: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class EscalaAlteracaoLog(SQLModel, table=True):
    """Histórico de alterações no módulo Escala operacional."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    shift: str = Field(default="Manhã", index=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)  # motorista da escala
    campo: str = Field(index=True)  # motorista | caminhao | ajudante | status
    valor_anterior: Optional[str] = None
    valor_novo: Optional[str] = None
    altered_by: Optional[str] = None  # email/username do usuário
    altered_at: datetime = Field(default_factory=datetime.now, index=True)


class RouteInsertLog(SQLModel, table=True):
    """Log de inserção de cliente na rota (entrega/separacao) para validar dia e horário."""
    id: Optional[int] = Field(default=None, primary_key=True)
    route_id: int = Field(foreign_key="route.id", index=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    route_date: str = Field(index=True)  # YYYY-MM-DD da rota
    shift: str = Field(default="Manhã", index=True)
    inserted_at: datetime = Field(default_factory=datetime.now, index=True)  # Data/hora em que foi inserido
    source: str = Field(default="import_entregas", index=True)  # import_entregas | separacao_manual | mobile_start | admin_manual
    created_by: Optional[str] = Field(default=None, index=True)  # Usuário que inseriu (se disponível)


class RouteImportBatchLog(SQLModel, table=True):
    """Um registro por envio/importação de planilha de entregas (auditoria de lotes)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    occurred_at: datetime = Field(default_factory=datetime.now, index=True)
    created_by: Optional[str] = Field(default=None, index=True)
    route_date: str = Field(index=True)
    shift: str = Field(default="Manhã", index=True)
    source: str = Field(default="import_entregas", index=True)
    filename: Optional[str] = Field(default=None, max_length=512)
    stops_imported: int = Field(default=0)
    route_codes_in_file: int = Field(default=0)
    rows_replaced_before: int = Field(default=0)
    issues_count: int = Field(default=0)
    warnings_count: int = Field(default=0)
    pre_registered_clients: int = Field(default=0)
    partial: bool = Field(default=False)


class DeliverySession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    employee_id: int = Field(foreign_key="employee.id", index=True)
    status: str = Field(default="open", index=True)  # open, closed
    vehicle_plate: str = Field(index=True)
    helpers_json: Optional[str] = None  # JSON list de employee_id
    km_departure: Optional[float] = None
    km_return: Optional[float] = None
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    reopen_reason: Optional[str] = None  # Motivo ao reabrir rota fechada no mesmo dia
    # Última posição reportada pelo app mobile (ping durante a rota)
    driver_last_lat: Optional[float] = None
    driver_last_lon: Optional[float] = None
    driver_last_location_at: Optional[datetime] = None


class DeliveryWhatsAppBatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    route_group_key: str = Field(index=True)
    route_date: str = Field(index=True)
    shift: str = Field(default="Manhã", index=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    vehicle_plate: str = Field(index=True)
    status: str = Field(default="pendente_envio", index=True)
    provider_name: Optional[str] = Field(default=None, index=True)
    operator_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    operator_label: Optional[str] = Field(default=None, index=True)
    total_clients: int = Field(default=0)
    eligible_count: int = Field(default=0)
    sent_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    ignored_count: int = Field(default=0)
    no_contact_count: int = Field(default=0)
    invalid_count: int = Field(default=0)
    blocked_count: int = Field(default=0)
    already_sent_count: int = Field(default=0)
    is_retry: bool = Field(default=False, index=True)
    preview_message: Optional[str] = None
    request_payload_json: Optional[str] = None
    response_json: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    started_at: Optional[datetime] = Field(default=None, index=True)
    finished_at: Optional[datetime] = Field(default=None, index=True)


class DeliveryWhatsAppItem(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("batch_id", "client_id", name="uq_deliverywhatsappitem_batch_client"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="deliverywhatsappbatch.id", index=True)
    route_group_key: str = Field(index=True)
    route_id: Optional[int] = Field(default=None, foreign_key="route.id", index=True)
    route_date: str = Field(index=True)
    shift: str = Field(default="Manhã", index=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    vehicle_plate: str = Field(index=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    client_name: Optional[str] = Field(default=None, index=True)
    phone_raw: Optional[str] = None
    phone_normalized: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="pendente_envio", index=True)
    attempt_number: int = Field(default=1)
    provider_name: Optional[str] = Field(default=None, index=True)
    provider_message_id: Optional[str] = Field(default=None, index=True)
    operator_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    operator_label: Optional[str] = Field(default=None, index=True)
    request_payload_json: Optional[str] = None
    response_json: Optional[str] = None
    failure_reason: Optional[str] = None
    sent_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)


class DeliveryAuthRequest(SQLModel, table=True):
    """Solicitação de autorização para iniciar entrega fora do raio de 300 m."""
    id: Optional[int] = Field(default=None, primary_key=True)
    route_id: int = Field(foreign_key="route.id", index=True)
    driver_id: int = Field(foreign_key="employee.id", index=True)
    client_name: Optional[str] = None
    distancia_metros: Optional[float] = None
    motivo: Optional[str] = None
    status: str = Field(default="pending", index=True)  # pending | approved | denied
    requested_at: datetime = Field(default_factory=datetime.now, index=True)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    obs: Optional[str] = None


class VehicleLocation(SQLModel, table=True):
    """Registro de localização de veículos em tempo real."""
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    plate: str = Field(index=True)
    latitude: float
    longitude: float
    timestamp: datetime = Field(default_factory=datetime.now, index=True)


class PortariaCheck(SQLModel, table=True):
    """Registro de conferência da portaria: saída (azul) e chegada (verde)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    delivery_session_id: int = Field(foreign_key="deliverysession.id", index=True)
    check_type: str = Field(index=True)  # saida | chegada
    date: str = Field(index=True)  # YYYY-MM-DD
    driver_id: int = Field(foreign_key="employee.id", index=True)
    driver_name: str = Field(index=True)
    helpers_text: str = Field(default="")
    vehicle_plate: str = Field(index=True)
    km: float = Field(default=0.0)
    peso_total_kg: float = Field(default=0.0)
    valor_total: float = Field(default=0.0)
    porteiro_confirmed_at: datetime = Field(default_factory=datetime.now, index=True)
    porteiro_employee_id: int = Field(foreign_key="employee.id", index=True)


# --- Checklist Operacional (Transpaleteira) ---

class TranspalletEquipment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    status: str = Field(default="available", index=True)  # available, blocked
    blocked_reason: Optional[str] = None
    blocked_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    released_by: Optional[str] = None
    last_checklist_id: Optional[int] = Field(default=None, index=True)

class EquipmentTicket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    equipment_code: str = Field(index=True)
    title: Optional[str] = None
    description: str
    shift: Optional[str] = Field(default=None, index=True)
    priority: str = Field(default="medium", index=True)  # low, medium, high, critical
    severity: str = Field(default="low", index=True)  # low, high
    status: str = Field(default="open", index=True)  # open, in_progress, resolved, closed
    images: List[str] = Field(default=[], sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None
    closed_at: Optional[datetime] = None
    closed_by: Optional[str] = None
    email_sent_at: Optional[datetime] = None
    email_error: Optional[str] = None
    maintenance_email_sent_at: Optional[datetime] = None
    maintenance_email_error: Optional[str] = None

class EquipmentTicketEvent(SQLModel, table=True):
    """Eventos de histórico para chamados de equipamento"""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="equipmentticket.id", index=True)
    event_type: str = Field(index=True)  # created, status_change, comment, resolved, closed
    description: str
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now, index=True)

class ChecklistEmailRecipient(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)

class AbsenceAlertRecipient(SQLModel, table=True):
    """Destinatários de e-mail para alertas de ausência (falta, folga, atestado)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    name: Optional[str] = None  # Nome do destinatário (ex: "Jurídico", "RH")
    alert_type: str = Field(default="absent", index=True)  # absent, dayoff, sick
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)

class AbsenceAlertLog(SQLModel, table=True):
    """Registro de e-mails de advertência enviados - TRAVA DE SEGURANÇA contra duplicados"""
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    absence_date: str = Field(index=True)  # Data da falta (YYYY-MM-DD)
    sent_at: datetime = Field(default_factory=datetime.now, index=True)
    sent_by: Optional[str] = None  # Quem registrou a falta
    recipients_count: int = Field(default=0)  # Quantos destinatários receberam

class TranspalletChecklist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    equipment_code: str = Field(index=True)
    odometer_km: Optional[float] = Field(default=None, index=True)  # KM do hodômetro (obrigatório para caminhão)
    date: str = Field(index=True)  # YYYY-MM-DD
    shift: str = Field(index=True)
    status: str = Field(default="submitted", index=True)  # submitted, reviewed, approved, rejected

    items: dict = Field(default={}, sa_column=Column(JSON))
    nonconforming_keys: List[str] = Field(default=[], sa_column=Column(JSON))
    observations: Optional[str] = None
    images: List[str] = Field(default=[], sa_column=Column(JSON))
    critical_flag: bool = Field(default=False)

    submitted_at: datetime = Field(default_factory=datetime.now)
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    review_comment: Optional[str] = None

    edited_at: Optional[datetime] = None
    edited_by: Optional[str] = None
    edit_comment: Optional[str] = None
    previous_observations: Optional[str] = None
    previous_equipment_code: Optional[str] = None

    xp_transaction_id: Optional[int] = Field(default=None, index=True)
    maintenance_email_sent_at: Optional[datetime] = None
    maintenance_email_error: Optional[str] = None

# --- Smart Flow Hierarchical Models ---

class Sector(SQLModel, table=True):
    """Setor principal (ex: Recebimento, Expedição)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)  # Nome do setor
    shift: str = Field(index=True)  # Manhã, Tarde, Noite
    max_employees: int = Field(default=0)  # Limite de vagas do setor
    order: int = Field(default=0)  # Ordem de exibição
    color: Optional[str] = Field(default="blue")  # Cor do card
    icon: Optional[str] = Field(default="box")  # Ícone
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # Relacionamentos
    subsectors: List["SubSector"] = Relationship(back_populates="sector", cascade_delete=True)

class SubSector(SQLModel, table=True):
    """Sub-setor dentro de um setor (ex: Doca 1, Linha 2)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    sector_id: int = Field(foreign_key="sector.id", index=True)
    name: str  # Nome do sub-setor
    max_employees: int = Field(default=0)  # Limite de vagas do sub-setor
    order: int = Field(default=0)  # Ordem de exibição
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Relacionamentos
    sector: Sector = Relationship(back_populates="subsectors")
    allocations: List["EmployeeAllocation"] = Relationship(back_populates="subsector", cascade_delete=True)

class EmployeeAllocation(SQLModel, table=True):
    """Alocação de colaborador em sub-setor (por dia/turno)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    shift: str = Field(index=True)  # Manhã, Tarde, Noite
    employee_id: int = Field(foreign_key="employee.id", index=True)
    subsector_id: int = Field(foreign_key="subsector.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Relacionamentos
    subsector: SubSector = Relationship(back_populates="allocations")

class EmployeeRoutine(SQLModel, table=True):
    """Rotina diária do colaborador (Presente, Falta, Férias, etc)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    shift: str = Field(index=True)  # Manhã, Tarde, Noite
    employee_id: int = Field(foreign_key="employee.id", index=True)
    routine: str = Field(default="present")  # present, absent, sick, vacation, away
    
    # New fields for Mobile Routine Management
    start_time: Optional[str] = None # HH:MM
    end_time: Optional[str] = None # HH:MM
    status: str = Field(default="open") # open, closed (locked)
    
    # Audit Reopen
    reopened_at: Optional[datetime] = None
    reopened_by: Optional[str] = None
    reopened_reason: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class XPLedger(SQLModel, table=True):
    """Ledger contábil para auditoria de XP"""
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    transaction_type: str = Field(index=True) # SHIFT_CLOSED, JOB_DONE, RECORD_BONUS, REWARD_REDEEM, ADJUSTMENT
    points: float
    reference_id: Optional[str] = None # e.g. "shift_123", "job_456"
    note: Optional[str] = None

# --- Gamification V2 Models ---

class GameLevel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    level: int = Field(index=True, unique=True)
    name: str
    min_xp: int
    min_months: int = Field(default=0) # Time in company requirement
    badge_image: str = Field(default="badge_default.png")

class GameXPTransaction(SQLModel, table=True):
    """
    Robust Ledger for XP Audit.
    Replaces simple XPLedger with Approval Status.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    amount: float
    source_type: str = Field(index=True) # shift_auto, manager_adjustment, achievement_grant
    status: str = Field(default="provisional", index=True) # provisional, confirmed, rejected
    reason: str
    manager_id: Optional[str] = None # Username/ID of manager who approved
    created_at: datetime = Field(default_factory=datetime.now)
    confirmed_at: Optional[datetime] = None

class GameAchievement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: Optional[str] = Field(default=None, index=True) # e.g. "marathon_100t"
    name: str
    description: str
    icon: str = Field(default="🏆") # emoji or lucide icon name
    xp_reward: int = Field(default=0)
    category: str = Field(default="general") # production, attendance, health, tenure, social, special
    trigger_type: str = Field(default="manual") # auto_production, auto_attendance, auto_health, auto_tenure, auto_streak, manual
    trigger_value: Optional[str] = None # JSON with trigger conditions
    trigger_rule: Optional[str] = None # Legacy - JSON or key for logic
    is_manual: bool = Field(default=False) # Legacy - If true, only managers can grant

class EmployeeAchievement(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    achievement_id: int = Field(foreign_key="gameachievement.id", index=True)
    earned_at: datetime = Field(default_factory=datetime.now)
    status: str = Field(default="pending") # pending, approved
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


class GameConfiguration(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str 
    description: str
    category: str 
    updated_at: datetime = Field(default_factory=datetime.now)


# --- Substitution History ---

class SubstitutionHistory(SQLModel, table=True):
    """Histórico de substituições de colaboradores"""
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Colaborador que saiu (foi substituído)
    original_employee_id: int = Field(foreign_key="employee.id", index=True)
    original_employee_name: str  # Nome para referência histórica
    original_registration_id: str  # Matrícula para referência histórica
    
    # Colaborador que entrou (substituto)
    new_employee_id: int = Field(foreign_key="employee.id", index=True)
    new_employee_name: str  # Nome para referência histórica
    new_registration_id: str  # Matrícula para referência histórica
    
    # Detalhes da substituição
    reason: str = Field(index=True)  # fired (demitido), away (afastado)
    substitution_date: datetime = Field(default_factory=datetime.now, index=True)
    
    # Informações adicionais
    shift: Optional[str] = None  # Turno do colaborador
    sector: Optional[str] = None  # Setor/Centro de custo
    observations: Optional[str] = None  # Observações adicionais
    
    # Quem registrou
    registered_by: Optional[str] = None  # Nome/email de quem registrou
    created_at: datetime = Field(default_factory=datetime.now)


# --- Pallet Truck Counting System ---

class PalletSector(SQLModel, table=True):
    """Setor onde as paleteiras ficam alocadas"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)  # Ex: Expedição, Câmara, Recebimento
    description: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    order: int = Field(default=0)  # Ordem de exibição
    created_at: datetime = Field(default_factory=datetime.now)

class PalletCount(SQLModel, table=True):
    """Registro de contagem diária de paleteira (por número individual)"""
    id: Optional[int] = Field(default=None, primary_key=True)
    pallet_number: str = Field(index=True)  # Número da paleteira (ex: "001", "A12", etc)
    date: str = Field(index=True)  # YYYY-MM-DD
    shift: str = Field(index=True)  # Manhã, Tarde, Noite
    sector_id: Optional[int] = Field(default=None, index=True)  # Removido foreign_key para permitir null
    employee_id: int = Field(foreign_key="employee.id", index=True)  # Quem registrou
    
    # Status da paleteira neste dia
    # found = Encontrada na contagem
    # missing = Não foi encontrada (estava no dia anterior)
    # new = Nova (não existia no dia anterior)
    # maintenance = Foi para manutenção
    status: str = Field(default="found", index=True)
    
    observations: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now, index=True)

class PalletMaintenanceTicket(SQLModel, table=True):
    """Chamado de manutenção de paleteira"""
    id: Optional[int] = Field(default=None, primary_key=True)
    pallet_number: str = Field(index=True)  # Número original da paleteira
    sector_id: Optional[int] = Field(default=None, foreign_key="palletsector.id", index=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)  # Quem abriu
    
    # Detalhes do problema
    issue_type: str = Field(default="other", index=True)  # battery, wheel, fork, hydraulic, electrical, other
    description: str
    priority: str = Field(default="medium", index=True)  # low, medium, high, critical
    images: List[str] = Field(default=[], sa_column=Column(JSON))
    
    # Status do chamado
    # open = Aguardando manutenção
    # in_progress = Em manutenção
    # returned = Retornou da manutenção
    # replaced = Trocada (veio outra no lugar)
    # closed = Fechado
    status: str = Field(default="open", index=True)
    
    # Rastreio de troca
    returned_pallet_number: Optional[str] = Field(default=None, index=True)  # Número da paleteira que voltou (pode ser diferente)
    return_date: Optional[datetime] = None
    return_notes: Optional[str] = None
    
    # E-mail
    email_sent_at: Optional[datetime] = None
    email_error: Optional[str] = None
    
    # Audit
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None
    closed_by: Optional[str] = None

class PalletCountEmailRecipient(SQLModel, table=True):
    """Destinatários de e-mail para alertas de contagem de paleteiras"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: Optional[str] = None  # Nome/Descrição (ex: "Manutenção", "Supervisor")
    alert_type: str = Field(default="all", index=True)  # all, missing, maintenance
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


# --- Módulo Líder: Tarefas enviadas para colaboradores ---

class LeaderTask(SQLModel, table=True):
    """Tarefa criada pelo líder para um ou mais colaboradores."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    priority: str = Field(default="medium", index=True)  # low, medium, high
    status: str = Field(default="sent", index=True)  # draft, sent, cancelled
    created_by: Optional[str] = None  # username do líder
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    due_at: Optional[datetime] = None
    recipient_employee_ids: List[int] = Field(default=[], sa_column=Column(JSON))  # lista de employee.id


class LeaderTaskResponse(SQLModel, table=True):
    """Resposta do colaborador à tarefa (visto / concluído)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="leadertask.id", index=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    seen_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


# --- Módulo GM: Ordens de Serviço Operacionais ---

class OperationalTask(SQLModel, table=True):
    """Ordem de serviço operacional criada pelo GM para líderes."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    category: str = Field(default="geral", index=True)  # limpeza, conferencia, manutencao, seguranca, geral
    priority: str = Field(default="medium", index=True)  # low, medium, high
    
    # Recorrência
    recurrence_type: str = Field(default="once", index=True)  # once, daily, weekly, monthly
    recurrence_days: List[int] = Field(default=[], sa_column=Column(JSON))  # [0,1,2,3,4,5,6] para semanal (0=seg)
    recurrence_day_of_month: Optional[int] = None  # 1-31 para mensal
    
    # Horário e duração
    scheduled_time: Optional[str] = None  # HH:MM
    estimated_duration_minutes: Optional[int] = None
    
    # Setor (opcional)
    sector_id: Optional[int] = Field(default=None, index=True)
    
    # Responsáveis
    recipient_user_ids: List[int] = Field(default=[], sa_column=Column(JSON))  # lista de user.id (líderes)
    
    # Requisitos
    requires_photo: bool = Field(default=False)
    requires_note: bool = Field(default=False)
    
    # Status e validade
    status: str = Field(default="active", index=True)  # active, paused, archived
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    
    # Auditoria
    created_by: Optional[str] = None  # username do GM
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now)


class OperationalTaskExecution(SQLModel, table=True):
    """Execução diária de uma ordem de serviço por um líder."""
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="operationaltask.id", index=True)
    scheduled_date: str = Field(index=True)  # YYYY-MM-DD
    user_id: int = Field(foreign_key="user.id", index=True)  # líder responsável
    
    # Status: pending, in_progress, completed, postponed, not_done, justified
    status: str = Field(default="pending", index=True)
    
    # Timestamps de execução
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Adiamento
    postponed_to: Optional[str] = None  # Nova data YYYY-MM-DD
    postpone_reason: Optional[str] = None
    
    # Não realizado
    not_done_reason: Optional[str] = None
    
    # Observações e evidências
    note: Optional[str] = None
    photo_urls: List[str] = Field(default=[], sa_column=Column(JSON))
    
    # Aprovação pelo GM (opcional)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    
    # Auditoria
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_at: datetime = Field(default_factory=datetime.now)


# --- Módulo Devoluções / Ocorrências de Entrega ---

class DevolucaoResponsabilidade(SQLModel, table=True):
    """Cadastro oficial: setor responsável (MERCADO, COMERCIAL, LOGÍSTICA)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True, unique=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class DevolucaoMotivo(SQLModel, table=True):
    """Cadastro oficial: motivo de devolução (normalizado)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    responsabilidade_id: int = Field(foreign_key="devolucaoresponsabilidade.id", index=True)
    nome_normalizado: str = Field(default="", index=True)  # para match flexível
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class Devolucao(SQLModel, table=True):
    """Registro de devolução/ocorrência de entrega."""
    id: Optional[int] = Field(default=None, primary_key=True)
    route_id: Optional[int] = Field(default=None, foreign_key="route.id", index=True)  # Parada vinculada (opcional)
    data_romaneio: str = Field(index=True)  # YYYY-MM-DD
    data_entrega: str = Field(index=True)  # YYYY-MM-DD
    client_id: int = Field(foreign_key="client.id", index=True)
    vendedor_id: int = Field(foreign_key="employee.id", index=True)
    motorista_id: int = Field(foreign_key="employee.id", index=True)
    ajudante_id: Optional[int] = Field(default=None, foreign_key="employee.id", index=True)
    valor: float = Field(default=0.0)
    motivo_id: int = Field(foreign_key="devolucaomotivo.id", index=True)
    observacao: Optional[str] = None  # Observação do motorista (somente leitura na edição pelo gestor)
    observacao_gestor: Optional[str] = None  # Observação do gestor (por que alterou a devolução)
    observacao_gestor_edited_by: Optional[str] = None  # Usuário do sistema que editou
    observacao_gestor_edited_at: Optional[datetime] = None
    responsabilidade_id: int = Field(foreign_key="devolucaoresponsabilidade.id", index=True)
    # Campos calculados
    dia: int = Field(default=0, index=True)
    semana: int = Field(default=0, index=True)
    acima_300: str = Field(default="NAO", index=True)  # SIM | NAO
    cluster: Optional[str] = Field(default=None, index=True)
    # Auditoria
    source: str = Field(default="manual", index=True)  # EXCEL | MANUAL | MOBILE | WEB
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    # Idempotência: hash para evitar duplicatas
    idempotency_hash: Optional[str] = Field(default=None, index=True, unique=True)
    # Duplicata de planilha quando já existe registro mobile/rota (mobile prevalece)
    duplicate_of_id: Optional[int] = Field(default=None, foreign_key="devolucao.id", index=True)
    # DUPLICATE_EXCEL | ORPHAN_ROUTE | ""
    validation_status: str = Field(default="", index=True)


class DevolucaoImportBatch(SQLModel, table=True):
    """Lote de importação de devoluções (Preview → Commit)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: Optional[str] = None
    status: str = Field(default="preview", index=True)  # preview | committed
    total_rows: int = Field(default=0)
    valid_count: int = Field(default=0)
    invalid_count: int = Field(default=0)
    pending_count: int = Field(default=0)  # fila de pendências
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now, index=True)
    committed_at: Optional[datetime] = None


class DevolucaoImportRowError(SQLModel, table=True):
    """Erro por linha na importação."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="devolucaoimportbatch.id", index=True)
    row_index: int = Field(index=True)
    column_name: Optional[str] = None
    value: Optional[str] = None
    reason: str = Field(index=True)
    raw_row_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class DevolucaoStaging(SQLModel, table=True):
    """Fila de pendências: linha com referência não cadastrada (opcional)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: Optional[int] = Field(default=None, foreign_key="devolucaoimportbatch.id", index=True)
    row_index: int = Field(index=True)
    status: str = Field(default="PENDENTE_VALIDACAO", index=True)  # PENDENTE_VALIDACAO | RESOLVIDO | REJEITADO
    data_romaneio: Optional[str] = None
    data_entrega: Optional[str] = None
    codigo_cliente: Optional[str] = None
    nome_cliente: Optional[str] = None
    codigo_vendedor: Optional[str] = None
    nome_motorista: Optional[str] = None
    valor: float = Field(default=0.0)
    motivo_raw: Optional[str] = None
    responsabilidade_raw: Optional[str] = None
    observacao: Optional[str] = None
    ajudante_raw: Optional[str] = None
    validation_errors: Optional[str] = None  # JSON com erros
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    devolucao_id: Optional[int] = Field(default=None, foreign_key="devolucao.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now, index=True)


class DevolucaoAjusteResponsabilidade(SQLModel, table=True):
    """Ajuste de responsabilidade do motorista e do ajudante na devolução (só para visão consolidada; não altera dados reais)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    devolucao_id: int = Field(foreign_key="devolucao.id", index=True, unique=True)
    responsavel_motorista: bool = Field(default=True, index=True)  # True = conta para % do motorista; False = não conta
    responsavel_ajudante: bool = Field(default=True, index=True)  # True = conta para % do ajudante; False = não conta
    updated_at: datetime = Field(default_factory=datetime.now, index=True)
    updated_by: Optional[str] = None


# --- Painel Informativo (avisos para colaboradores no /dashboard) ---

class InformativeBulletin(SQLModel, table=True):
    """Aviso exibido no painel Informativo (texto e/ou imagem)."""
    __tablename__ = "informative_bulletin"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    body: Optional[str] = None  # texto livre; quebras de linha viram <br> no template
    # URL externa (https) ou data URI — preferida para produção (persistente).
    image_url: Optional[str] = Field(default=None, max_length=500)
    # Upload no servidor: caminho público /media/informativo/… (disco Render) ou legado /static/uploads/informativo/…
    uploaded_image_path: Optional[str] = Field(default=None, max_length=500)
    link_url: Optional[str] = Field(default=None, max_length=500)  # matéria / site (abre em nova aba)
    sort_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class InformativePanelConfig(SQLModel, table=True):
    """Configuração global do carrossel do painel /dashboard (singleton id=1)."""
    __tablename__ = "informative_panel_config"
    id: int = Field(default=1, primary_key=True)
    carousel_interval_seconds: int = Field(default=8, ge=4, le=120)
    audio_enabled: bool = Field(default=False)
    audio_url: Optional[str] = Field(default=None, max_length=500)
    audio_playlist: Optional[str] = Field(default=None, max_length=4000)
    audio_youtube_url: Optional[str] = Field(default=None, max_length=500)
    audio_volume: int = Field(default=35, ge=0, le=100)


class InformativeMonthlyReturn(SQLModel, table=True):
    """Índice de devolução mensal (painel informativo): %, valores e receita (receita só para meta 2%)."""
    __tablename__ = "informative_monthly_return"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_informative_monthly_return_year_month"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    year: int = Field(index=True)
    month: int = Field(ge=1, le=12, index=True)  # 1=jan … 12=dez
    pct_devolucao: Optional[float] = Field(default=None)  # % sobre receita (informado)
    valor_devolucao: Optional[float] = Field(default=None)  # R$ devolvido
    receita: Optional[float] = Field(default=None)  # R$ receita (não exibida no gráfico; meta = 2% disso)
    use_system_kpi: bool = Field(default=False)  # % e valor R$: rotas delivery no mês civil + Devolucao por data_romaneio; receita manual
    updated_at: datetime = Field(default_factory=datetime.now)


# --- Documentos Institucionais (Processos e Padronização) ---

class DocSetor(SQLModel, table=True):
    """Setores/áreas para geração de códigos documentais (LOG, RH, OP, DIR, etc.)."""
    __tablename__ = "doc_setor"
    id: Optional[int] = Field(default=None, primary_key=True)
    sigla: str = Field(index=True, unique=True, max_length=10)
    nome: str = Field(max_length=100)
    ativo: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class DocInstitucional(SQLModel, table=True):
    """Documentos institucionais padronizados: POP, IT, FOR, REL, COM, POL, CHK."""
    __tablename__ = "doc_institucional"
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo_documento: str = Field(index=True, max_length=3)  # POP, IT, FOR, REL, COM, POL, CHK
    codigo: str = Field(index=True, unique=True, max_length=50)
    titulo: str = Field(max_length=255)
    versao: int = Field(default=1)
    data_emissao: Optional[str] = Field(default=None, max_length=10)  # YYYY-MM-DD
    area_responsavel: str = Field(index=True, max_length=50)
    elaborado_por: str = Field(max_length=100)
    revisado_por: Optional[str] = Field(default=None, max_length=100)
    aprovado_por: Optional[str] = Field(default=None, max_length=100)
    classificacao: str = Field(default="Interno", max_length=50)
    status: str = Field(default="rascunho", index=True)  # rascunho, em_revisao, aprovado, obsoleto, arquivado
    conteudo: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)


class DocInstitucionalRevisao(SQLModel, table=True):
    """Histórico de revisões de documentos institucionais."""
    __tablename__ = "doc_institucional_revisao"
    id: Optional[int] = Field(default=None, primary_key=True)
    documento_id: int = Field(foreign_key="doc_institucional.id", index=True)
    versao: int = Field(index=True)
    alteracao: Optional[str] = Field(default=None)
    responsavel: str = Field(max_length=100)
    data_revisao: datetime = Field(default_factory=datetime.now)
