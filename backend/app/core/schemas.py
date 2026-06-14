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

class ProjectPriority(str, enum.Enum):
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"

class FacilityType(str, enum.Enum):
    RAITARU = "Raitaru"
    AZBEL   = "Azbel"
    SOTIYO  = "Sotiyo"
    ATHANOR = "Athanor"   # reactions (medium refinery)
    TATARA  = "Tatara"    # reactions (large refinery)
    OTHER   = "Other"

class OrganisationType(str, enum.Enum):
    PERSONAL    = "Personal"
    CORPORATION = "Corporation"

class ProductionStatus(str, enum.Enum):
    PLANNING    = "Planning"
    PREPARING   = "Preparing"
    IN_PROGRESS = "In Progress"
    COMPLETED   = "Completed"
    CANCELLED   = "Cancelled"

class ProductionTarget(str, enum.Enum):
    REACTIONS = "Reactions"
    REFUELING = "Refueling"
    SELL      = "Sell"
    INTERNAL  = "Internal"
    OTHER     = "Other"