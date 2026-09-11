from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class AiRequestSchema(BaseModel):
    message: str
    thread_id: str
    

class ChatRequestSchema(BaseModel):
    title: str


class ChatResponseSchema(BaseModel):
    id: int
    thread_id: str
    title: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class BatchRequestSchema(BaseModel):
    thread_id: str
    prompts: list[str]
    

class GenerateTaskSchema(BaseModel):
    id: int
    title: str
    description: str
    files: list[str] = Field(default_factory=list)
    reason: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["pending", "queued", "running", "completed", "failed"] = "pending"
    

class HeavyAnalysisSchema(BaseModel):
    analysis: str
    tasks: list[GenerateTaskSchema] = Field(default_factory=list)
    
    
class TaskResponseSchema(BaseModel):
    id: int
    title: str
    description: str
    files: list[str]
    reason: str
    status: str

    class Config:
        from_attributes = True