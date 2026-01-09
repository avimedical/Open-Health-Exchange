"""
Deterministic identifier generation utilities for FHIR resources.

Supports both modern UUID-based format and Jenkins One-at-a-Time hash
for backwards compatibility with the inwithings implementation.
"""

import hashlib
import uuid
from datetime import datetime

from django.conf import settings
from django.utils import timezone


def jenkins_one_at_a_time_hash(data: str) -> int:
    """
    Jenkins One-at-a-Time hash function for deterministic identifier generation.

    This matches the inwithings implementation for idempotent resource creation.
    The hash is based on a SHA256 digest of the input, then processed through
    the Jenkins algorithm.

    Args:
        data: Input string to hash (e.g., "patientId:datetime:loincCode")

    Returns:
        32-bit unsigned integer hash value
    """
    # First create SHA256 digest like inwithings does
    sha256_digest = hashlib.sha256(data.encode("utf-8")).digest()

    # Apply Jenkins One-at-a-Time hash
    hash_mask = 0x7FFFFFFF  # 31-bit mask as used in inwithings
    hash_value = 0

    for byte in sha256_digest:
        hash_value = (hash_value + byte) & hash_mask
        hash_value = (hash_value + (hash_value << 10)) & hash_mask
        hash_value ^= hash_value >> 6

    hash_value = (hash_value + (hash_value << 3)) & hash_mask
    hash_value ^= hash_value >> 11
    hash_value = (hash_value + (hash_value << 15)) & hash_mask

    return hash_value


def format_datetime_for_identifier(timestamp: datetime) -> str:
    """
    Format datetime for identifier generation, matching inwithings format.

    inwithings uses: DateTime.toUTC().toISO().replace('T', ' ')
    Example: "2024-01-15 14:30:00.000Z"

    Args:
        timestamp: Datetime to format

    Returns:
        Formatted datetime string
    """
    # Ensure UTC timezone
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    # Format matching inwithings: replace T with space
    iso_string = timestamp.isoformat()
    return iso_string.replace("T", " ")


def generate_observation_identifier(
    patient_id: str,
    timestamp: datetime,
    loinc_code: str,
    secondary_loinc_code: str | None = None,
    strategy: str | None = None,
) -> str:
    """
    Generate a deterministic observation identifier.

    Args:
        patient_id: Patient/user identifier
        timestamp: Measurement timestamp
        loinc_code: Primary LOINC code
        secondary_loinc_code: Secondary LOINC code (for blood pressure)
        strategy: Override strategy ("modern" or "jenkins_hash")

    Returns:
        Deterministic identifier string
    """
    config = getattr(settings, "FHIR_COMPATIBILITY_CONFIG", {})
    effective_strategy = strategy or config.get("IDENTIFIER_STRATEGY", "jenkins_hash")

    # Format timestamp for identifier
    datetime_string = format_datetime_for_identifier(timestamp)

    if effective_strategy == "jenkins_hash":
        # inwithings format: hash of patientId:datetime:loincCode
        if secondary_loinc_code:
            # Blood pressure uses combined LOINC codes: systolic:diastolic
            hash_input = f"{patient_id}:{datetime_string}:{loinc_code}:{secondary_loinc_code}"
        else:
            hash_input = f"{patient_id}:{datetime_string}:{loinc_code}"

        hash_value = jenkins_one_at_a_time_hash(hash_input)
        return str(hash_value)
    else:
        # Modern format: UUID based on deterministic input
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
        if secondary_loinc_code:
            name = f"{patient_id}:{datetime_string}:{loinc_code}:{secondary_loinc_code}"
        else:
            name = f"{patient_id}:{datetime_string}:{loinc_code}"
        return str(uuid.uuid5(namespace, name))


def generate_resource_uuid(resource_type: str, identifier_base: str) -> str:
    """
    Generate a UUID for FHIR resource IDs.

    Args:
        resource_type: FHIR resource type (e.g., "Observation", "Device")
        identifier_base: Base string for UUID generation

    Returns:
        UUID string
    """
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
    name = f"{resource_type}:{identifier_base}"
    return str(uuid.uuid5(namespace, name))


def get_identifier_system(provider: str) -> str:
    """
    Get the identifier system URL for a provider.

    Args:
        provider: Provider name (e.g., "withings", "fitbit")

    Returns:
        Identifier system URL
    """
    config = getattr(settings, "FHIR_COMPATIBILITY_CONFIG", {})
    template = config.get("IDENTIFIER_SYSTEM_TEMPLATE", "https://api.{provider}.com/health-data")
    return template.format(provider=provider)


# LOINC codes for blood pressure components (used for identifier generation)
BLOOD_PRESSURE_LOINC = {
    "panel": "85354-9",
    "systolic": "8480-6",
    "diastolic": "8462-4",
}
