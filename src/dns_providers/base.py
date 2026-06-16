#!/usr/bin/env python3
"""
Base DNS Provider Interface
Defines the abstract interface all DNS providers must implement
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict


@dataclass
class DNSRecord:
    """Represents a DNS record"""
    record_type: str  # A, AAAA, CNAME, TXT, MX, NS
    name: str         # Record name/subdomain
    value: str        # Record value
    ttl: int = 3600   # Time to live
    priority: Optional[int] = None  # For MX records
    record_id: Optional[str] = None  # Provider-specific ID


class DNSProvider(ABC):
    """
    Abstract base class for DNS provider integrations

    Each provider implementation should:
    1. Authenticate with provider API
    2. List existing records
    3. Create new records
    4. Update existing records
    5. Delete records
    """

    def __init__(self, credentials: Dict[str, str]):
        """
        Initialize DNS provider with credentials

        Args:
            credentials: Provider-specific authentication credentials
        """
        self.credentials = credentials
        self._validate_credentials()

    @abstractmethod
    def _validate_credentials(self) -> None:
        """
        Validate that required credentials are present

        Raises:
            ValueError: If required credentials are missing
        """
        pass

    @abstractmethod
    def list_records(self, domain: str, record_type: Optional[str] = None) -> List[DNSRecord]:
        """
        List DNS records for a domain

        Args:
            domain: Domain name (e.g., "example.com")
            record_type: Optional filter by record type (A, CNAME, etc.)

        Returns:
            List of DNSRecord objects

        Raises:
            Exception: If API call fails
        """
        pass

    @abstractmethod
    def create_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """
        Create a new DNS record

        Args:
            domain: Domain name
            record: DNSRecord to create

        Returns:
            Created DNSRecord with record_id populated

        Raises:
            Exception: If creation fails
        """
        pass

    @abstractmethod
    def update_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """
        Update an existing DNS record

        Args:
            domain: Domain name
            record: DNSRecord with record_id and updated values

        Returns:
            Updated DNSRecord

        Raises:
            Exception: If update fails or record doesn't exist
        """
        pass

    @abstractmethod
    def delete_record(self, domain: str, record_id: str) -> bool:
        """
        Delete a DNS record

        Args:
            domain: Domain name
            record_id: Provider-specific record ID

        Returns:
            True if successful

        Raises:
            Exception: If deletion fails
        """
        pass

    def sync_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """
        Sync a DNS record (create if doesn't exist, update if it does)

        Args:
            domain: Domain name
            record: DNSRecord to sync

        Returns:
            Synced DNSRecord
        """
        # Find existing record
        existing_records = self.list_records(domain, record.record_type)
        existing = next((r for r in existing_records if r.name == record.name), None)

        if existing:
            # Update existing record
            record.record_id = existing.record_id
            return self.update_record(domain, record)
        else:
            # Create new record
            return self.create_record(domain, record)

    def get_zone_id(self, domain: str) -> Optional[str]:
        """
        Get zone ID for a domain (provider-specific)

        Some providers (like Cloudflare) use zone IDs.
        Override this method if needed.

        Args:
            domain: Domain name

        Returns:
            Zone ID or None if not applicable
        """
        return None
