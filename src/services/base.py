#!/usr/bin/env python3
"""
Base service class providing common functionality
"""
from typing import Optional
from logger import get_logger


class BaseService:
    """
    Base class for all service layer classes.

    Services contain business logic and orchestrate operations across repositories.
    They are domain-specific and handle complex workflows, validation, and
    cross-cutting concerns.
    """

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def _validate_required(self, value: any, field_name: str) -> None:
        """Validate that a required field is present"""
        if value is None or (isinstance(value, str) and not value.strip()):
            from error_handler import ValidationError
            raise ValidationError(
                f"{field_name} is required",
                solution=f"Please provide a valid {field_name}"
            )

    def _validate_slug(self, slug: str) -> None:
        """Validate project slug format"""
        import re
        if not re.match(r'^[a-z0-9_-]+$', slug):
            from error_handler import ValidationError
            raise ValidationError(
                f"Invalid slug format: '{slug}'",
                solution="Slug must contain only lowercase letters, numbers, hyphens, and underscores"
            )
