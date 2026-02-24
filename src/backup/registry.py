"""
Backup provider registry and factory
"""

from typing import Dict, Type, Optional, Any
from pathlib import Path

from src.backup.base import CloudBackupProvider
from src.logger import get_logger

logger = get_logger(__name__)


class BackupProviderRegistry:
    """Registry for backup providers"""

    _providers: Dict[str, Type[CloudBackupProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: Type[CloudBackupProvider]):
        """
        Register a backup provider.

        Args:
            name: Provider identifier (e.g., 'gdrive', 's3')
            provider_class: Provider class
        """
        cls._providers[name.lower()] = provider_class
        logger.debug(f"Registered backup provider: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[Type[CloudBackupProvider]]:
        """
        Get a provider class by name.

        Args:
            name: Provider identifier

        Returns:
            Provider class or None if not found
        """
        return cls._providers.get(name.lower())

    @classmethod
    def list_providers(cls) -> Dict[str, Dict[str, Any]]:
        """
        List all registered providers.

        Returns:
            Dict mapping provider names to metadata
        """
        providers = {}
        for name, provider_class in cls._providers.items():
            providers[name] = {
                'class': provider_class.__name__,
                'available': provider_class.is_available(),
                'friendly_name': provider_class.get_provider_name(),
                'required_config': provider_class.get_required_config(),
            }
        return providers

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a provider is registered"""
        return name.lower() in cls._providers


def get_provider(
    provider_name: str,
    config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> CloudBackupProvider:
    """
    Factory function to create a backup provider instance.

    Args:
        provider_name: Provider identifier (e.g., 'gdrive', 's3', 'dropbox')
        config: Provider configuration dict
        **kwargs: Additional configuration as keyword arguments

    Returns:
        Provider instance

    Raises:
        ValueError: If provider not found or not available
    """
    provider_class = BackupProviderRegistry.get(provider_name)

    if not provider_class:
        available = ', '.join(BackupProviderRegistry.list_providers().keys())
        raise ValueError(
            f"Unknown backup provider: {provider_name}. "
            f"Available providers: {available}"
        )

    if not provider_class.is_available():
        raise ValueError(
            f"Provider '{provider_name}' is not available. "
            f"Missing dependencies or configuration."
        )

    # Merge config and kwargs
    if config:
        kwargs.update(config)

    # Check required config
    required = provider_class.get_required_config()
    missing = [key for key in required if key not in kwargs]
    if missing:
        raise ValueError(
            f"Missing required configuration for {provider_name}: {', '.join(missing)}"
        )

    return provider_class(**kwargs)


def load_provider_from_config(config_path: Path) -> CloudBackupProvider:
    """
    Load provider from configuration file.

    Args:
        config_path: Path to JSON or YAML config file

    Returns:
        Provider instance

    Raises:
        ValueError: If config invalid or provider not found
    """
    import json

    if not config_path.exists():
        raise ValueError(f"Config file not found: {config_path}")

    # Parse config file
    with open(config_path) as f:
        if config_path.suffix in ['.yaml', '.yml']:
            try:
                import yaml
                config = yaml.safe_load(f)
            except ImportError:
                raise ValueError("PyYAML not installed. Cannot parse YAML config.")
        else:
            config = json.load(f)

    # Extract provider name
    provider_name = config.get('provider')
    if not provider_name:
        raise ValueError("Config must specify 'provider' key")

    # Get provider config
    provider_config = config.get('config', {})

    return get_provider(provider_name, provider_config)
