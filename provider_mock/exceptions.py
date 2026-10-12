class InvoiceException(Exception):
    """Base exception for provider invoice operations."""

    def __init__(self, message: str, code: str = "invoice_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class InvoiceNotFoundError(InvoiceException):
    """Raised when an invoice cannot be found by its ID."""

    def __init__(self, invoice_id: str) -> None:
        super().__init__(
            message=f"Invoice '{invoice_id}' not found",
            code="invoice_not_found",
        )
        self.invoice_id = invoice_id


class InvoiceAlreadyFinalError(InvoiceException):
    """Raised when attempting to modify an invoice that is already in a final state."""

    def __init__(self, invoice_id: str, current_status: str) -> None:
        super().__init__(
            message=f"Invoice '{invoice_id}' is in final state '{current_status}' and cannot be modified",
            code="invoice_already_final",
        )
        self.invoice_id = invoice_id
        self.current_status = current_status
