class IngestionError(Exception):
    """Base class for problems with an uploaded file."""


class UnsupportedFileTypeError(IngestionError):
    pass


class FileTooLargeError(IngestionError):
    pass


class InvalidDocumentError(IngestionError):
    """File is the right type but unreadable, empty, or has no extractable text."""


class DuplicateDocumentError(IngestionError):
    def __init__(self, existing_id: object) -> None:
        super().__init__(f"Document already ingested: {existing_id}")
        self.existing_id = existing_id
