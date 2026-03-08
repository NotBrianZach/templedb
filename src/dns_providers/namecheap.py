#!/usr/bin/env python3
"""
Namecheap DNS Provider
Uses Namecheap API for DNS management
"""

import requests
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict
from .base import DNSProvider, DNSRecord
from logger import get_logger

logger = get_logger(__name__)


class NamecheapDNSProvider(DNSProvider):
    """
    Namecheap DNS API integration

    Required credentials:
    - api_key: Namecheap API key
    - api_user: Namecheap username
    - client_ip: Your whitelisted IP address

    Documentation: https://www.namecheap.com/support/api/methods/
    """

    API_BASE = "https://api.namecheap.com/xml.response"

    def _validate_credentials(self) -> None:
        """Validate Namecheap credentials"""
        required = ['api_key', 'api_user', 'client_ip']
        missing = [k for k in required if k not in self.credentials]

        if missing:
            raise ValueError(f"Namecheap requires: {', '.join(required)}. Missing: {', '.join(missing)}")

    def _make_request(self, command: str, params: Dict[str, str]) -> ET.Element:
        """
        Make a request to Namecheap API

        Args:
            command: API command (e.g., namecheap.domains.dns.getHosts)
            params: Additional parameters

        Returns:
            XML response root element

        Raises:
            Exception: If API returns error
        """
        request_params = {
            'ApiUser': self.credentials['api_user'],
            'ApiKey': self.credentials['api_key'],
            'UserName': self.credentials['api_user'],
            'ClientIp': self.credentials['client_ip'],
            'Command': command,
        }
        request_params.update(params)

        response = requests.get(self.API_BASE, params=request_params)

        if response.status_code != 200:
            raise Exception(f"API request failed: {response.status_code}")

        root = ET.fromstring(response.text)

        # Check for API errors
        status = root.get('Status')
        if status != 'OK':
            errors = root.findall('.//{*}Error')
            error_messages = [e.text for e in errors]
            raise Exception(f"Namecheap API error: {', '.join(error_messages)}")

        return root

    def _parse_domain(self, domain: str) -> tuple[str, str]:
        """
        Parse domain into SLD and TLD

        Args:
            domain: Full domain (e.g., "example.com" or "sub.example.com")

        Returns:
            Tuple of (SLD, TLD) - e.g., ("example", "com")
        """
        parts = domain.split('.')

        # Handle subdomains - extract root domain
        if len(parts) > 2:
            # For "sub.example.com", we want ("example", "com")
            sld = parts[-2]
            tld = parts[-1]
        else:
            sld = parts[0]
            tld = parts[1] if len(parts) > 1 else ''

        return sld, tld

    def list_records(self, domain: str, record_type: Optional[str] = None) -> List[DNSRecord]:
        """List DNS records for a domain"""
        sld, tld = self._parse_domain(domain)

        root = self._make_request('namecheap.domains.dns.getHosts', {
            'SLD': sld,
            'TLD': tld,
        })

        records = []
        for host in root.findall('.//{*}host'):
            rec_type = host.get('Type')

            # Filter by type if specified
            if record_type and rec_type != record_type:
                continue

            hostname = host.get('Name')
            # Namecheap uses '@' for root domain
            if hostname == '@':
                full_name = f"{sld}.{tld}"
            else:
                full_name = f"{hostname}.{sld}.{tld}"

            record = DNSRecord(
                record_type=rec_type,
                name=full_name,
                value=host.get('Address'),
                ttl=int(host.get('TTL', 3600)),
                priority=int(host.get('MXPref')) if host.get('MXPref') else None,
                record_id=host.get('HostId')
            )
            records.append(record)

        logger.info(f"Found {len(records)} DNS records for {domain}")
        return records

    def create_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """
        Create a new DNS record

        Note: Namecheap doesn't have a direct "create" API.
        We need to get all records, add the new one, and update the entire list.
        """
        sld, tld = self._parse_domain(domain)

        # Get existing records
        existing_records = self.list_records(domain)

        # Add new record to the list
        existing_records.append(record)

        # Update all records
        self._update_all_records(sld, tld, existing_records)

        logger.info(f"Created DNS record: {record.name} ({record.record_type})")
        return record

    def update_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """
        Update an existing DNS record

        Note: Namecheap updates all records at once, so we fetch all,
        modify the target record, and update the entire list.
        """
        sld, tld = self._parse_domain(domain)

        # Get existing records
        existing_records = self.list_records(domain)

        # Find and update the record
        found = False
        for i, existing in enumerate(existing_records):
            if existing.name == record.name and existing.record_type == record.record_type:
                existing_records[i] = record
                found = True
                break

        if not found:
            raise Exception(f"Record not found: {record.name} ({record.record_type})")

        # Update all records
        self._update_all_records(sld, tld, existing_records)

        logger.info(f"Updated DNS record: {record.name} ({record.record_type})")
        return record

    def delete_record(self, domain: str, record_id: str) -> bool:
        """
        Delete a DNS record

        Note: Namecheap updates all records at once, so we fetch all,
        remove the target record, and update the entire list.
        """
        sld, tld = self._parse_domain(domain)

        # Get existing records
        existing_records = self.list_records(domain)

        # Remove the record
        filtered_records = [r for r in existing_records if r.record_id != record_id]

        if len(filtered_records) == len(existing_records):
            raise Exception(f"Record not found with ID: {record_id}")

        # Update all records
        self._update_all_records(sld, tld, filtered_records)

        logger.info(f"Deleted DNS record: {record_id}")
        return True

    def _update_all_records(self, sld: str, tld: str, records: List[DNSRecord]) -> None:
        """
        Update all DNS records for a domain

        This is how Namecheap API works - you must send all records at once.

        Args:
            sld: Second-level domain (e.g., "example")
            tld: Top-level domain (e.g., "com")
            records: List of all DNS records
        """
        params = {
            'SLD': sld,
            'TLD': tld,
        }

        # Build host parameters
        # Namecheap expects: HostName1, RecordType1, Address1, TTL1, MXPref1, etc.
        for i, record in enumerate(records, start=1):
            # Extract hostname from full name
            # e.g., "www.example.com" -> "www"
            full_domain = f"{sld}.{tld}"
            if record.name == full_domain:
                hostname = '@'
            elif record.name.endswith(f".{full_domain}"):
                hostname = record.name[:-len(full_domain)-1]
            else:
                hostname = record.name

            params[f'HostName{i}'] = hostname
            params[f'RecordType{i}'] = record.record_type
            params[f'Address{i}'] = record.value
            params[f'TTL{i}'] = str(record.ttl)

            if record.priority is not None:
                params[f'MXPref{i}'] = str(record.priority)

        self._make_request('namecheap.domains.dns.setHosts', params)
        logger.info(f"Updated all {len(records)} DNS records for {sld}.{tld}")
