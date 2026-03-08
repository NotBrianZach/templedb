#!/usr/bin/env python3
"""
Cloudflare DNS Provider
Uses Cloudflare API v4 for DNS management
"""

import requests
from typing import List, Optional, Dict
from .base import DNSProvider, DNSRecord
from logger import get_logger

logger = get_logger(__name__)


class CloudflareDNSProvider(DNSProvider):
    """
    Cloudflare DNS API integration

    Required credentials:
    - api_token: Cloudflare API token with DNS edit permissions
      OR
    - api_key: Global API key
    - email: Cloudflare account email

    Documentation: https://developers.cloudflare.com/api/operations/dns-records-for-a-zone-list-dns-records
    """

    API_BASE = "https://api.cloudflare.com/client/v4"

    def _validate_credentials(self) -> None:
        """Validate Cloudflare credentials"""
        # Support both API token (recommended) and legacy API key + email
        has_token = 'api_token' in self.credentials
        has_legacy = 'api_key' in self.credentials and 'email' in self.credentials

        if not (has_token or has_legacy):
            raise ValueError(
                "Cloudflare requires either 'api_token' OR ('api_key' + 'email')"
            )

    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        if 'api_token' in self.credentials:
            return {
                'Authorization': f"Bearer {self.credentials['api_token']}",
                'Content-Type': 'application/json'
            }
        else:
            return {
                'X-Auth-Email': self.credentials['email'],
                'X-Auth-Key': self.credentials['api_key'],
                'Content-Type': 'application/json'
            }

    def get_zone_id(self, domain: str) -> str:
        """
        Get Cloudflare zone ID for a domain

        Args:
            domain: Domain name (e.g., "example.com")

        Returns:
            Zone ID

        Raises:
            Exception: If zone not found or API error
        """
        # Extract root domain (e.g., "sub.example.com" -> "example.com")
        parts = domain.split('.')
        if len(parts) > 2:
            root_domain = '.'.join(parts[-2:])
        else:
            root_domain = domain

        url = f"{self.API_BASE}/zones"
        params = {'name': root_domain}
        response = requests.get(url, headers=self._get_headers(), params=params)

        if response.status_code != 200:
            raise Exception(f"Failed to get zone ID: {response.text}")

        data = response.json()
        if not data.get('success') or not data.get('result'):
            raise Exception(f"Zone not found for domain: {domain}")

        return data['result'][0]['id']

    def list_records(self, domain: str, record_type: Optional[str] = None) -> List[DNSRecord]:
        """List DNS records for a domain"""
        zone_id = self.get_zone_id(domain)
        url = f"{self.API_BASE}/zones/{zone_id}/dns_records"

        params = {}
        if record_type:
            params['type'] = record_type

        response = requests.get(url, headers=self._get_headers(), params=params)

        if response.status_code != 200:
            raise Exception(f"Failed to list records: {response.text}")

        data = response.json()
        if not data.get('success'):
            raise Exception(f"API error: {data.get('errors')}")

        records = []
        for item in data.get('result', []):
            record = DNSRecord(
                record_type=item['type'],
                name=item['name'],
                value=item['content'],
                ttl=item['ttl'],
                priority=item.get('priority'),
                record_id=item['id']
            )
            records.append(record)

        logger.info(f"Found {len(records)} DNS records for {domain}")
        return records

    def create_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """Create a new DNS record"""
        zone_id = self.get_zone_id(domain)
        url = f"{self.API_BASE}/zones/{zone_id}/dns_records"

        payload = {
            'type': record.record_type,
            'name': record.name,
            'content': record.value,
            'ttl': record.ttl,
        }

        if record.priority is not None:
            payload['priority'] = record.priority

        response = requests.post(url, headers=self._get_headers(), json=payload)

        if response.status_code not in (200, 201):
            raise Exception(f"Failed to create record: {response.text}")

        data = response.json()
        if not data.get('success'):
            raise Exception(f"API error: {data.get('errors')}")

        result = data['result']
        record.record_id = result['id']

        logger.info(f"Created DNS record: {record.name} ({record.record_type})")
        return record

    def update_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """Update an existing DNS record"""
        if not record.record_id:
            raise ValueError("record_id required for update")

        zone_id = self.get_zone_id(domain)
        url = f"{self.API_BASE}/zones/{zone_id}/dns_records/{record.record_id}"

        payload = {
            'type': record.record_type,
            'name': record.name,
            'content': record.value,
            'ttl': record.ttl,
        }

        if record.priority is not None:
            payload['priority'] = record.priority

        response = requests.put(url, headers=self._get_headers(), json=payload)

        if response.status_code != 200:
            raise Exception(f"Failed to update record: {response.text}")

        data = response.json()
        if not data.get('success'):
            raise Exception(f"API error: {data.get('errors')}")

        logger.info(f"Updated DNS record: {record.name} ({record.record_type})")
        return record

    def delete_record(self, domain: str, record_id: str) -> bool:
        """Delete a DNS record"""
        zone_id = self.get_zone_id(domain)
        url = f"{self.API_BASE}/zones/{zone_id}/dns_records/{record_id}"

        response = requests.delete(url, headers=self._get_headers())

        if response.status_code != 200:
            raise Exception(f"Failed to delete record: {response.text}")

        data = response.json()
        if not data.get('success'):
            raise Exception(f"API error: {data.get('errors')}")

        logger.info(f"Deleted DNS record: {record_id}")
        return True
