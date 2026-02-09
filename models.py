from datetime import datetime, time
from typing import Optional, List
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
    name: str
    admission_date: Optional[datetime] = None
    cost_center: Optional[str] = None
    role: str # Cargo
    birthday: Optional[datetime] = None
    photo_url: Optional[str] = None
    
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

from sqlalchemy import Column, JSON
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

class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.now)

class Route(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True) # YYYY-MM-DD
    shift: str = Field(default="Manhã", index=True) # Manhã, Tarde, Noite
    employee_id: int = Field(foreign_key="employee.id")
    client_id: int = Field(foreign_key="client.id")
    start_time: str # HH:MM
    end_time: Optional[str] = None # HH:MM
    tonnage: float = 0.0
    status: str = "pending" # pending, completed
    created_at: datetime = Field(default_factory=datetime.now)

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

