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
    # active, vacation, away, fired
    status: str = Field(default="active")
    work_shift: str = Field(default="Manhã") # Manhã, Tarde, Noite
    



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
