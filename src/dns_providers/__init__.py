#!/usr/bin/env python3
"""
DNS Provider Integration
Supports automated DNS management via provider APIs
"""

from .base import DNSProvider, DNSRecord

__all__ = [
    'DNSProvider',
    'DNSRecord',
    'get_provider'
]


def get_provider(provider_name: str, credentials: dict) -> DNSProvider:
    """
    Factory function to get DNS provider instance

    Args:
        provider_name: Name of the DNS provider (cloudflare, namecheap, route53)
        credentials: Provider-specific credentials

    Returns:
        DNSProvider instance

    Raises:
        ValueError: If provider is not supported
        ImportError: If required dependencies are missing
    """
    provider_name_lower = provider_name.lower()

    # Lazy import providers to avoid import errors if dependencies aren't installed
    if provider_name_lower == 'cloudflare':
        try:
            from .cloudflare import CloudflareDNSProvider
            return CloudflareDNSProvider(credentials)
        except ImportError as e:
            raise ImportError(f"Cloudflare provider requires 'requests' library. Install with: pip install requests") from e

    elif provider_name_lower == 'namecheap':
        try:
            from .namecheap import NamecheapDNSProvider
            return NamecheapDNSProvider(credentials)
        except ImportError as e:
            raise ImportError(f"Namecheap provider requires 'requests' library. Install with: pip install requests") from e

    elif provider_name_lower == 'route53':
        try:
            from .route53 import Route53DNSProvider
            return Route53DNSProvider(credentials)
        except ImportError as e:
            raise ImportError(f"Route53 provider requires 'boto3' library. Install with: pip install boto3") from e

    else:
        raise ValueError(f"Unsupported DNS provider: {provider_name}. Supported: cloudflare, namecheap, route53")
