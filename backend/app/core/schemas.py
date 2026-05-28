import enum
from pydantic import BaseModel

class EmployeeType(str, enum.Enum):
    OWNER= "OWNER"
    ADMIN = "ADMIN"
    SENIOR = "SENIOR"
    JUNIOR = "JUNIOR"
    INTERN = "INTERN"
    OTHER = "OTHER"
    INACTIVE = "INACTIVE"

class ProjectsType(str, enum.Enum):
    INTERNAL = "INTERNAL"
    SELL = "SELL"
    ACCUMULATION = "ACCUMULATION"
    OTHER = "OTHER"

class ProjectsStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PAUSE = "PAUSE"
    DELETED = "DELETED"