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
    
    shift_id: Optional[int] = Field(default=None, foreign_key="shift.id")
    shift: Optional[Shift] = Relationship(back_populates="events")

    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    employee: Optional[Employee] = Relationship(back_populates="events")

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True)
    password_hash: str # In simplistic version we will just store plain/hashed, but for now hardcoded in auth logic

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
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
