"""
Health Data Publisher for managing FHIR health data resources
"""

import logging
from typing import Any

from django.conf import settings

from ingestors.health_data_constants import HealthDataType, Provider

from .client import FHIRClient

logger = logging.getLogger(__name__)


class HealthDataPublisher:
    """Publishes and manages FHIR health data resources"""

    def __init__(self):
        self.fhir_client = FHIRClient()

    def publish_health_observations(self, observations: list[dict[str, Any]], batch_size: int = None) -> dict[str, Any]:
        """
        Publish health observations to the FHIR server

        Args:
            observations: List of FHIR Observation resources
            batch_size: Number of observations to publish in each batch

        Returns:
            Publishing result with statistics
        """
        result = {
            "total_observations": len(observations),
            "published_successfully": 0,
            "failed_observations": 0,
            "errors": [],
            "published_ids": [],
            "batch_results": [],
        }

        # Use default batch size from settings if not provided
        if batch_size is None:
            batch_size = settings.BATCH_SIZES["PUBLISHER"]

        try:
            # Process observations in batches
            for i in range(0, len(observations), batch_size):
                batch = observations[i : i + batch_size]
                batch_result = self._publish_observation_batch(batch, i // batch_size + 1)

                result["published_successfully"] += batch_result.get("successful", 0)
                result["failed_observations"] += batch_result.get("failed", 0)
                result["errors"].extend(batch_result.get("errors", []))
                result["published_ids"].extend(batch_result.get("published_ids", []))
                result["batch_results"].append(batch_result)

                logger.info(
                    f"Batch {i // batch_size + 1}: {batch_result['successful']} successful, "
                    f"{batch_result['failed']} failed"
                )

            result["success"] = result["failed_observations"] == 0

            logger.info(
                f"Health data publishing completed: {result['published_successfully']} successful, "
                f"{result['failed_observations']} failed"
            )

            return result

        except Exception as e:
            logger.error(f"Error publishing health observations: {e}")
            result["errors"].append(str(e))
            result["success"] = False
            return result

    def _publish_observation_batch(self, observations: list[dict[str, Any]], batch_number: int) -> dict[str, Any]:
        """Publish a batch of observations"""
        batch_result = {
            "batch_number": batch_number,
            "total": len(observations),
            "successful": 0,
            "failed": 0,
            "errors": [],
            "published_ids": [],
        }

        for observation in observations:
            try:
                # Check for existing observation to avoid duplicates
                existing_observation = self._find_existing_observation(observation)

                if existing_observation:
                    logger.debug(
                        f"Skipping duplicate observation with identifier {observation.get('identifier', [{}])[0].get('value')}"
                    )
                    continue

                # Publish new observation
                published_observation = self.fhir_client.create_resource("Observation", observation)
                batch_result["successful"] = batch_result.get("successful", 0) + 1
                published_ids = batch_result.get("published_ids", [])
                published_ids.append(published_observation.get("id"))
                batch_result["published_ids"] = published_ids

                logger.debug(f"Published observation {published_observation.get('id')}")

            except Exception as e:
                batch_result["failed"] = batch_result.get("failed", 0) + 1
                error_msg = f"Failed to publish observation: {e}"
                errors = batch_result.get("errors", [])
                errors.append(error_msg)
                batch_result["errors"] = errors
                logger.error(error_msg)

        return batch_result

    def _find_existing_observation(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        """Check if an observation with the same identifier already exists"""
        try:
            identifiers = observation.get("identifier", [])
            if not identifiers:
                return None

            # Use the secondary identifier from our system
            secondary_identifier = None
            for identifier in identifiers:
                if identifier.get("use") == "secondary":
                    secondary_identifier = identifier
                    break

            if not secondary_identifier:
                return None

            system = secondary_identifier.get("system")
            value = secondary_identifier.get("value")

            if not system or not value:
                return None

            # Search for existing observation
            existing = self.fhir_client.find_resource_by_identifier("Observation", system, value)

            return existing

        except Exception as e:
            logger.debug(f"Error checking for existing observation: {e}")
            return None

    def publish_health_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """
        Publish a FHIR transaction bundle of health data

        Args:
            bundle: FHIR transaction bundle

        Returns:
            Bundle publishing result
        """
        try:
            # Submit transaction bundle
            result = self.fhir_client.create_resource("Bundle", bundle)

            # Analyze bundle response
            published_count = 0
            failed_count = 0
            errors = []

            if "entry" in result:
                for entry in result["entry"]:
                    response = entry.get("response", {})
                    status = response.get("status", "")

                    if status.startswith("201"):  # Created
                        published_count += 1
                    else:
                        failed_count += 1
                        if "outcome" in entry:
                            errors.append(str(entry["outcome"]))

            return {
                "success": failed_count == 0,
                "bundle_id": result.get("id"),
                "total_entries": len(bundle.get("entry", [])),
                "published_successfully": published_count,
                "failed_entries": failed_count,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Error publishing health data bundle: {e}")
            return {
                "success": False,
                "error": str(e),
                "total_entries": len(bundle.get("entry", [])),
                "published_successfully": 0,
                "failed_entries": len(bundle.get("entry", [])),
                "errors": [str(e)],
            }

    def get_health_data_statistics(
        self, patient_reference: str, data_types: list[HealthDataType] | None = None
    ) -> dict[str, Any]:
        """
        Get health data statistics for a patient

        Args:
            patient_reference: FHIR Patient reference
            data_types: Optional list of specific data types to analyze

        Returns:
            Statistics about patient's health data
        """
        try:
            # Search for observations for this patient
            search_params = {"subject": patient_reference}
            bundle = self.fhir_client.search_resource("Observation", search_params)

            observations = []
            if bundle.get("total", 0) > 0:
                for entry in bundle.get("entry", []):
                    observations.append(entry.get("resource"))

            # Analyze observations
            stats: dict[str, Any] = {
                "total_observations": len(observations),
                "observations_by_type": {},
                "observations_by_provider": {},
                "latest_observations": {},
                "date_range": {},
            }

            if not observations:
                return stats

            # Analyze each observation
            dates = []
            for observation in observations:
                # Analyze by data type (LOINC code)
                code_info = observation.get("code", {})
                loinc_code = None
                for coding in code_info.get("coding", []):
                    if coding.get("system") == "http://loinc.org":
                        loinc_code = coding.get("code")
                        break

                if loinc_code:
                    stats["observations_by_type"][loinc_code] = stats["observations_by_type"].get(loinc_code, 0) + 1

                # Analyze by provider (from meta.tag)
                meta = observation.get("meta", {})
                provider = "unknown"

                # Look for provider tag
                tags = meta.get("tag", [])
                for tag in tags:
                    if tag.get("system") == "https://open-health-exchange.com/provider":
                        provider = tag.get("code", "unknown")
                        logger.info(f"Found provider tag: '{provider}'")
                        break

                if provider == "unknown":
                    logger.warning(f"No provider tag found in observation meta: {meta}")

                stats["observations_by_provider"][provider] = stats["observations_by_provider"].get(provider, 0) + 1

                # Track dates
                effective_date = observation.get("effectiveDateTime")
                if effective_date:
                    dates.append(effective_date)

                    # Track latest observation for each type
                    if loinc_code:
                        current_latest = stats["latest_observations"].get(loinc_code)
                        if not current_latest or effective_date > current_latest:
                            stats["latest_observations"][loinc_code] = effective_date

            # Calculate date range
            if dates:
                stats["date_range"] = {"earliest": min(dates), "latest": max(dates)}

            return stats

        except Exception as e:
            logger.error(f"Error getting health data statistics for {patient_reference}: {e}")
            return {"error": str(e), "total_observations": 0}

    def delete_health_data_by_provider(self, patient_reference: str, provider: Provider) -> dict[str, Any]:
        """
        Delete all health data observations for a patient from a specific provider

        Args:
            patient_reference: FHIR Patient reference
            provider: Provider to delete data for

        Returns:
            Deletion result
        """
        try:
            # Search for observations from this provider
            search_params = {"subject": patient_reference, "_tag": f"#{provider.value}"}

            bundle = self.fhir_client.search_resource("Observation", search_params)
            observations = []

            if bundle.get("total", 0) > 0:
                for entry in bundle.get("entry", []):
                    observations.append(entry.get("resource"))

            # Delete each observation
            deleted_count = 0
            errors = []

            for observation in observations:
                try:
                    observation_id = observation.get("id")
                    if observation_id:
                        self.fhir_client.delete_resource("Observation", observation_id)
                        deleted_count += 1
                        logger.debug(f"Deleted observation {observation_id}")
                except Exception as e:
                    error_msg = f"Failed to delete observation {observation.get('id')}: {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            return {
                "success": len(errors) == 0,
                "total_found": len(observations),
                "deleted_count": deleted_count,
                "failed_count": len(errors),
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Error deleting health data for provider {provider.value}: {e}")
            return {"success": False, "error": str(e), "deleted_count": 0}
