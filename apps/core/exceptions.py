class DomainError(Exception):
    """Base for business-rule violations; views show str(exc) to the user."""


class InvalidTransition(DomainError):
    pass


class ComplaintNotAllowed(DomainError):
    pass


class WorkOrderStateError(DomainError):
    pass


class AccessoryStateError(DomainError):
    pass
