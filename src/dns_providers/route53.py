#!/usr/bin/env python3
"""
AWS Route53 DNS Provider
Uses boto3 for Route53 DNS management
"""

from typing import List, Optional, Dict
from .base import DNSProvider, DNSRecord
from logger import get_logger

logger = get_logger(__name__)


class Route53DNSProvider(DNSProvider):
    """
    AWS Route53 DNS API integration

    Required credentials:
    - aws_access_key_id: AWS access key
    - aws_secret_access_key: AWS secret key
    - region: AWS region (default: us-east-1)

    Optional:
    - aws_session_token: For temporary credentials

    Documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/route53.html
    """

    def __init__(self, credentials: Dict[str, str]):
        """Initialize Route53 provider"""
        super().__init__(credentials)

        try:
            import boto3
            self.boto3 = boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for Route53 provider. "
                "Install with: pip install boto3"
            )

        # Initialize Route53 client
        region = credentials.get('region', 'us-east-1')
        self.client = self.boto3.client(
            'route53',
            aws_access_key_id=credentials['aws_access_key_id'],
            aws_secret_access_key=credentials['aws_secret_access_key'],
            aws_session_token=credentials.get('aws_session_token'),
            region_name=region
        )

    def _validate_credentials(self) -> None:
        """Validate Route53 credentials"""
        required = ['aws_access_key_id', 'aws_secret_access_key']
        missing = [k for k in required if k not in self.credentials]

        if missing:
            raise ValueError(f"Route53 requires: {', '.join(required)}. Missing: {', '.join(missing)}")

    def get_zone_id(self, domain: str) -> str:
        """
        Get Route53 hosted zone ID for a domain

        Args:
            domain: Domain name

        Returns:
            Zone ID (without /hostedzone/ prefix)

        Raises:
            Exception: If zone not found
        """
        # Ensure domain ends with dot for Route53
        if not domain.endswith('.'):
            domain = domain + '.'

        try:
            response = self.client.list_hosted_zones_by_name(DNSName=domain, MaxItems='1')

            if not response['HostedZones']:
                raise Exception(f"No hosted zone found for {domain}")

            zone = response['HostedZones'][0]
            zone_name = zone['Name']

            # Check if zone name matches (Route53 returns zones alphabetically)
            if not domain.endswith(zone_name):
                raise Exception(f"No hosted zone found for {domain}")

            # Extract zone ID (format: /hostedzone/Z1234567890ABC)
            zone_id = zone['Id'].split('/')[-1]
            return zone_id

        except Exception as e:
            raise Exception(f"Failed to get zone ID: {e}")

    def list_records(self, domain: str, record_type: Optional[str] = None) -> List[DNSRecord]:
        """List DNS records for a domain"""
        zone_id = self.get_zone_id(domain)

        try:
            # Route53 paginates results
            records = []
            paginator = self.client.get_paginator('list_resource_record_sets')

            for page in paginator.paginate(HostedZoneId=zone_id):
                for record_set in page['ResourceRecordSets']:
                    rec_type = record_set['Type']

                    # Filter by type if specified
                    if record_type and rec_type != record_type:
                        continue

                    # Route53 can have multiple values per record set
                    if 'ResourceRecords' in record_set:
                        for resource_record in record_set['ResourceRecords']:
                            record = DNSRecord(
                                record_type=rec_type,
                                name=record_set['Name'].rstrip('.'),
                                value=resource_record['Value'].rstrip('.') if rec_type in ['CNAME', 'NS'] else resource_record['Value'],
                                ttl=record_set.get('TTL', 300),
                                record_id=f"{record_set['Name']}:{rec_type}"  # Composite ID
                            )
                            records.append(record)

                    # Handle alias records
                    elif 'AliasTarget' in record_set:
                        record = DNSRecord(
                            record_type='ALIAS',
                            name=record_set['Name'].rstrip('.'),
                            value=record_set['AliasTarget']['DNSName'].rstrip('.'),
                            ttl=0,  # Alias records don't have TTL
                            record_id=f"{record_set['Name']}:ALIAS"
                        )
                        records.append(record)

            logger.info(f"Found {len(records)} DNS records for {domain}")
            return records

        except Exception as e:
            raise Exception(f"Failed to list records: {e}")

    def create_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """Create a new DNS record"""
        zone_id = self.get_zone_id(domain)

        # Ensure name ends with dot for Route53
        name = record.name if record.name.endswith('.') else record.name + '.'

        try:
            change_batch = {
                'Changes': [{
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': name,
                        'Type': record.record_type,
                        'TTL': record.ttl,
                        'ResourceRecords': [{'Value': record.value}]
                    }
                }]
            }

            response = self.client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch=change_batch
            )

            record.record_id = f"{name}:{record.record_type}"
            logger.info(f"Created DNS record: {record.name} ({record.record_type})")
            return record

        except Exception as e:
            raise Exception(f"Failed to create record: {e}")

    def update_record(self, domain: str, record: DNSRecord) -> DNSRecord:
        """Update an existing DNS record"""
        zone_id = self.get_zone_id(domain)

        # Ensure name ends with dot for Route53
        name = record.name if record.name.endswith('.') else record.name + '.'

        try:
            change_batch = {
                'Changes': [{
                    'Action': 'UPSERT',  # Create or update
                    'ResourceRecordSet': {
                        'Name': name,
                        'Type': record.record_type,
                        'TTL': record.ttl,
                        'ResourceRecords': [{'Value': record.value}]
                    }
                }]
            }

            response = self.client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch=change_batch
            )

            logger.info(f"Updated DNS record: {record.name} ({record.record_type})")
            return record

        except Exception as e:
            raise Exception(f"Failed to update record: {e}")

    def delete_record(self, domain: str, record_id: str) -> bool:
        """Delete a DNS record"""
        zone_id = self.get_zone_id(domain)

        # Parse composite record_id (format: "name:type")
        try:
            name, rec_type = record_id.split(':', 1)
        except ValueError:
            raise ValueError(f"Invalid record_id format: {record_id}. Expected 'name:type'")

        # Ensure name ends with dot
        if not name.endswith('.'):
            name = name + '.'

        try:
            # Get the record to delete (need its current values)
            existing_records = self.list_records(domain, rec_type)
            record_to_delete = next((r for r in existing_records if r.name == name.rstrip('.')), None)

            if not record_to_delete:
                raise Exception(f"Record not found: {name} ({rec_type})")

            change_batch = {
                'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': {
                        'Name': name,
                        'Type': rec_type,
                        'TTL': record_to_delete.ttl,
                        'ResourceRecords': [{'Value': record_to_delete.value}]
                    }
                }]
            }

            response = self.client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch=change_batch
            )

            logger.info(f"Deleted DNS record: {record_id}")
            return True

        except Exception as e:
            raise Exception(f"Failed to delete record: {e}")
