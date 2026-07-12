"""Security exceptions mapped to authentication and authorization failures."""

from ecos.core.exceptions import EcosError


class AuthenticationError(EcosError):
    """Raised when credentials or tokens are missing, invalid or expired."""

    def __init__(self, message: str = "authentication required") -> None:
        super().__init__(message=message, code="AUTHENTICATION_FAILED")


class AuthorizationError(EcosError):
    """Raised when an authenticated principal lacks permission."""

    def __init__(self, message: str = "permission denied") -> None:
        super().__init__(message=message, code="AUTHORIZATION_DENIED")


class CrossTenantAccessError(AuthorizationError):
    """Raised when a principal attempts to access another organization."""

    def __init__(self) -> None:
        super().__init__("cross-tenant access denied")
