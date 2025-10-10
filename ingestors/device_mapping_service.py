"""
Modern device mapping service - Provider-agnostic, cached, type-safe
Maps provider device IDs to FHIR Device UUIDs using Django cache backend
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from publishers.fhir.client import FHIRClient

from .constants import Provider

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class DeviceQuery:
    """Immutable device query for batch operations"""

    provider: Provider
    device_id: str

    @property
    def cache_key(self) -> str:
        """Generate cache key for this query"""
        prefix = settings.DEVICE_MAPPING["CACHE_PREFIX"]
        return f"{prefix}:{self.provider.value}:{self.device_id}"


class DeviceMappingService:
    """
    Modern device mapping service using unified batch operations

    All operations go through a single core method for consistency
    Uses Django cache backend with configurable TTL
    Provider-agnostic design using settings configuration
    """

    def __init__(self, fhir_client: FHIRClient | None = None) -> None:
        self.fhir_client = fhir_client or FHIRClient()
        self.config = settings.DEVICE_MAPPING

    def get_fhir_device_reference(self, provider: Provider, device_id: str) -> str | None:
        """
        Get FHIR Device reference for a single provider device ID
        Wrapper around unified batch method
        """
        if not device_id:
            return None

        query = DeviceQuery(provider=provider, device_id=device_id)
        results = self.get_device_references([query])
        return results.get(device_id)

    def bulk_map_devices(self, provider: Provider, device_ids: list[str]) -> dict[str, str | None]:
        """
        Bulk map multiple provider device IDs to FHIR Device references
        Wrapper around unified batch method
        """
        if not device_ids:
            return {}

        queries = [DeviceQuery(provider=provider, device_id=device_id) for device_id in device_ids if device_id]
        return self.get_device_references(queries)

    def get_device_references(self, queries: list[DeviceQuery]) -> dict[str, str | None]:
        """
        Unified method handling all device reference lookups
        Single source of truth for cache + FHIR operations
        """
        if not queries:
            return {}

        try:
            # Phase 1: Batch cache lookup
            results, uncached_queries = self._batch_cache_lookup(queries)

            logger.info(
                f"Cache performance: {len(results)}/{len(queries)} hits, {len(uncached_queries)} FHIR lookups needed"
            )

            # Phase 2: Batch FHIR search for cache misses
            if uncached_queries:
                fhir_results = self._batch_fhir_search(uncached_queries)
                results.update(fhir_results)

                # Phase 3: Batch cache storage
                self._batch_cache_store(uncached_queries, fhir_results)

            return results

        except Exception as e:
            logger.error(f"Device mapping batch operation failed: {e}")
            # Return empty results for failed operations
            return {query.device_id: None for query in queries}

    def _batch_cache_lookup(self, queries: list[DeviceQuery]) -> tuple[dict[str, str | None], list[DeviceQuery]]:
        """Unified cache lookup using Django's get_many for efficiency"""
        cache_keys = {query.cache_key: query for query in queries}

        try:
            # Single cache operation instead of multiple individual gets
            cached_values = cache.get_many(list(cache_keys.keys()))

            results = {}
            uncached_queries = []

            for cache_key, query in cache_keys.items():
                if cached_value := cached_values.get(cache_key):
                    # Type safety - ensure we got a string back
                    if isinstance(cached_value, str) and cached_value != "NOT_FOUND":
                        results[query.device_id] = cached_value
                        logger.debug(f"Cache HIT: {query.device_id} -> {cached_value}")
                        continue

                uncached_queries.append(query)
                logger.debug(f"Cache MISS: {query.device_id}")

            return results, uncached_queries

        except Exception as e:
            logger.warning(f"Cache lookup failed: {e}")
            # Fallback to FHIR for all queries
            return {}, queries

    def _batch_fhir_search(self, queries: list[DeviceQuery]) -> dict[str, str | None]:
        """Unified FHIR search with provider-specific identifier systems"""
        results = {}

        # Group queries by provider for efficiency
        by_provider: dict[Provider, list[DeviceQuery]] = defaultdict(list)
        for query in queries:
            by_provider[query.provider].append(query)

        for provider, provider_queries in by_provider.items():
            identifier_system = self._get_identifier_system(provider)

            for query in provider_queries:
                try:
                    device_uuid = self._search_single_device(identifier_system, query.device_id)
                    results[query.device_id] = f"Device/{device_uuid}" if device_uuid else None

                except Exception as e:
                    logger.error(f"FHIR search failed for {provider.value}:{query.device_id}: {e}")
                    results[query.device_id] = None

        return results

    def _search_single_device(self, identifier_system: str, device_id: str) -> str | None:
        """Single device FHIR search - consolidated logic"""
        search_params = {"identifier": f"{identifier_system}|{device_id}", "_count": 1}

        logger.debug(f"FHIR search: {search_params}")
        search_result = self.fhir_client.search_resource("Device", search_params)

        if entries := search_result.get("entry", []):
            if device_resource := entries[0].get("resource", {}):
                if device_uuid := device_resource.get("id"):
                    logger.debug(f"FHIR found device {device_id} -> {device_uuid}")
                    return device_uuid

        logger.debug(f"FHIR device not found: {device_id}")
        return None

    def _batch_cache_store(self, queries: list[DeviceQuery], results: dict[str, str | None]) -> None:
        """Unified cache storage using Django's set_many for efficiency"""
        positive_cache = {}
        negative_cache = {}

        for query in queries:
            result = results.get(query.device_id)

            match result:
                case str() as device_ref:
                    positive_cache[query.cache_key] = device_ref
                case None:
                    negative_cache[f"{query.cache_key}:not_found"] = "NOT_FOUND"

        try:
            # Batch cache operations
            if positive_cache:
                cache.set_many(positive_cache, timeout=self.config["CACHE_TTL"])
                logger.debug(f"Cached {len(positive_cache)} positive results")

            if negative_cache:
                cache.set_many(negative_cache, timeout=self.config["NEGATIVE_CACHE_TTL"])
                logger.debug(f"Cached {len(negative_cache)} negative results")

        except Exception as e:
            logger.warning(f"Cache storage failed: {e}")

    def _get_identifier_system(self, provider: Provider) -> str:
        """Provider-agnostic identifier system lookup from settings"""
        systems = self.config["IDENTIFIER_SYSTEMS"]

        match provider.value:
            case system_key if system_key in systems:
                return systems[system_key]
            case _:
                # Fallback pattern for unknown providers
                return f"https://api.{provider.value}.com/device-id"

    def clear_cache(self) -> None:
        """Clear device mapping cache (development/testing only)"""
        logger.warning(
            "Full cache pattern deletion not supported with Django cache. "
            "Use cache.clear() for full clear or wait for TTL expiration."
        )

    def get_cache_stats(self) -> dict[str, str | int]:
        """Get cache configuration and status"""
        return {
            "cache_backend": str(cache),
            "cache_ttl_hours": self.config["CACHE_TTL"] // 3600,
            "negative_cache_ttl_hours": self.config["NEGATIVE_CACHE_TTL"] // 3600,
            "cache_prefix": self.config["CACHE_PREFIX"],
            "batch_size": self.config["BATCH_SIZE"],
            "supported_providers": list(self.config["IDENTIFIER_SYSTEMS"].keys()),
        }


# Global service instance
_device_mapping_service: DeviceMappingService | None = None


def get_device_mapping_service() -> DeviceMappingService:
    """Lazy singleton for global service instance"""
    global _device_mapping_service
    if _device_mapping_service is None:
        _device_mapping_service = DeviceMappingService()
    return _device_mapping_service


def get_fhir_device_reference(provider: Provider, provider_device_id: str) -> str | None:
    """
    Convenience function for single device mapping

    Args:
        provider: Health data provider (fitbit, withings)
        provider_device_id: Device ID from provider API

    Returns:
        FHIR Device reference like "Device/uuid" or None if not found
    """
    return get_device_mapping_service().get_fhir_device_reference(provider, provider_device_id)


def bulk_map_devices(provider: Provider, provider_device_ids: list[str]) -> dict[str, str | None]:
    """
    Convenience function for bulk device mapping

    Args:
        provider: Health data provider
        provider_device_ids: List of device IDs from provider API

    Returns:
        Dictionary mapping provider_device_id -> FHIR Device reference
    """
    return get_device_mapping_service().bulk_map_devices(provider, provider_device_ids)
