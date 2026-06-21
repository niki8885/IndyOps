import enum


class EmployeeType(str, enum.Enum):
    OWNER = "OWNER"
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
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FacilityType(str, enum.Enum):
    RAITARU = "Raitaru"
    AZBEL = "Azbel"
    SOTIYO = "Sotiyo"
    ATHANOR = "Athanor"  # reactions (medium refinery)
    TATARA = "Tatara"  # reactions (large refinery)
    OTHER = "Other"


class OrganisationType(str, enum.Enum):
    PERSONAL = "Personal"
    CORPORATION = "Corporation"


class Visibility(str, enum.Enum):
    """Sharing setting for organisations & facilities. ``private`` = owner-only (today's
    behaviour); ``public`` = others can follow (watch list) and use it; ``group`` = stub,
    reserved for future org/group sharing — behaves as private for now."""
    PRIVATE = "private"
    PUBLIC = "public"
    GROUP = "group"


class ProductionStatus(str, enum.Enum):
    PLANNING = "Planning"
    PREPARING = "Preparing"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class ProductionTarget(str, enum.Enum):
    REACTIONS = "Reactions"
    REFUELING = "Refueling"
    SELL = "Sell"
    INTERNAL = "Internal"
    OTHER = "Other"
