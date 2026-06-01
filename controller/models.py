from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

class ProjectStatus(str, Enum):
    PROVISIONING = "Provisioning"
    READY = "Ready"
    TERMINATING = "Terminating"

class ProjectSchema(BaseModel):
    id: str = Field(alias="_id")
    name: str
    namespace: str
    status: ProjectStatus = Field(default=ProjectStatus.PROVISIONING)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
