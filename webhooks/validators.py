"""
Webhook signature validation for secure webhook endpoints
Validates that webhooks are genuinely from health data providers
"""
import hmac
import hashlib
import base64
import logging
from typing import Optional

from django.conf import settings
from django.http import HttpRequest


logger = logging.getLogger(__name__)


class WebhookSignatureValidator:
    """Validates webhook signatures for security"""

    def validate_withings_signature(self, request: HttpRequest) -> bool:
        """
        Validate Withings webhook signature

        Withings sends a signature in the 'X-Withings-Signature' header
        The signature is an HMAC-SHA256 hash of the request body using the webhook secret
        """
        try:
            # Check if signature validation is enabled
            webhook_secret = getattr(settings, 'WITHINGS_WEBHOOK_SECRET', None)
            if not webhook_secret:
                logger.warning("WITHINGS_WEBHOOK_SECRET not configured - skipping signature validation")
                return True  # Allow in development/testing

            # Get signature from header
            signature_header = request.META.get('HTTP_X_WITHINGS_SIGNATURE')
            if not signature_header:
                logger.error("Missing X-Withings-Signature header")
                return False

            # Calculate expected signature
            body = request.body
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                body,
                hashlib.sha256
            ).hexdigest()

            # Withings might prefix with algorithm name
            if signature_header.startswith('sha256='):
                provided_signature = signature_header[7:]  # Remove 'sha256=' prefix
            else:
                provided_signature = signature_header

            # Compare signatures using secure comparison
            is_valid = hmac.compare_digest(expected_signature, provided_signature)

            if not is_valid:
                logger.warning(f"Invalid Withings webhook signature. Expected: {expected_signature[:8]}..., Got: {provided_signature[:8]}...")

            return is_valid

        except Exception as e:
            logger.error(f"Error validating Withings webhook signature: {e}")
            return False

    def validate_fitbit_signature(self, request: HttpRequest) -> bool:
        """
        Validate Fitbit webhook signature

        Fitbit sends a signature in the 'X-Fitbit-Signature' header
        The signature is a base64-encoded HMAC-SHA1 hash of the request body
        """
        try:
            # Check if signature validation is enabled
            client_secret = getattr(settings, 'SOCIAL_AUTH_FITBIT_SECRET', None)
            if not client_secret:
                logger.warning("SOCIAL_AUTH_FITBIT_SECRET not configured - skipping signature validation")
                return True  # Allow in development/testing

            # Get signature from header
            signature_header = request.META.get('HTTP_X_FITBIT_SIGNATURE')
            if not signature_header:
                logger.error("Missing X-Fitbit-Signature header")
                return False

            # Calculate expected signature (Fitbit uses HMAC-SHA1)
            body = request.body
            expected_signature = base64.b64encode(
                hmac.new(
                    client_secret.encode('utf-8'),
                    body,
                    hashlib.sha1
                ).digest()
            ).decode('utf-8')

            # Compare signatures using secure comparison
            is_valid = hmac.compare_digest(expected_signature, signature_header)

            if not is_valid:
                logger.warning(f"Invalid Fitbit webhook signature. Expected: {expected_signature[:8]}..., Got: {signature_header[:8]}...")

            return is_valid

        except Exception as e:
            logger.error(f"Error validating Fitbit webhook signature: {e}")
            return False

    def validate_generic_signature(
        self,
        request: HttpRequest,
        secret: str,
        signature_header_name: str = 'HTTP_X_WEBHOOK_SIGNATURE',
        algorithm: str = 'sha256'
    ) -> bool:
        """
        Validate generic webhook signature

        Args:
            request: Django HTTP request
            secret: Webhook secret for HMAC calculation
            signature_header_name: Name of the signature header
            algorithm: Hash algorithm ('sha256', 'sha1', 'md5')
        """
        try:
            if not secret:
                logger.warning("No webhook secret provided - skipping signature validation")
                return True

            # Get signature from header
            signature_header = request.META.get(signature_header_name)
            if not signature_header:
                logger.error(f"Missing signature header: {signature_header_name}")
                return False

            # Get hash algorithm
            hash_algorithm = getattr(hashlib, algorithm, None)
            if not hash_algorithm:
                logger.error(f"Unsupported hash algorithm: {algorithm}")
                return False

            # Calculate expected signature
            body = request.body
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                body,
                hash_algorithm
            ).hexdigest()

            # Handle different signature formats
            provided_signature = signature_header
            if signature_header.startswith(f'{algorithm}='):
                provided_signature = signature_header[len(f'{algorithm}='):]

            # Compare signatures using secure comparison
            is_valid = hmac.compare_digest(expected_signature, provided_signature)

            if not is_valid:
                logger.warning(f"Invalid webhook signature. Expected: {expected_signature[:8]}..., Got: {provided_signature[:8]}...")

            return is_valid

        except Exception as e:
            logger.error(f"Error validating generic webhook signature: {e}")
            return False

    def validate_bearer_token(
        self,
        request: HttpRequest,
        expected_token: Optional[str] = None
    ) -> bool:
        """
        Validate webhook using Bearer token authentication

        Some providers use Bearer tokens instead of HMAC signatures
        """
        try:
            if not expected_token:
                logger.warning("No bearer token configured - skipping token validation")
                return True

            # Get Authorization header
            auth_header = request.META.get('HTTP_AUTHORIZATION')
            if not auth_header:
                logger.error("Missing Authorization header")
                return False

            if not auth_header.startswith('Bearer '):
                logger.error("Authorization header is not Bearer token format")
                return False

            provided_token = auth_header[7:]  # Remove 'Bearer ' prefix

            # Compare tokens using secure comparison
            is_valid = hmac.compare_digest(expected_token, provided_token)

            if not is_valid:
                logger.warning("Invalid Bearer token provided")

            return is_valid

        except Exception as e:
            logger.error(f"Error validating Bearer token: {e}")
            return False

    def is_signature_validation_enabled(self) -> bool:
        """Check if webhook signature validation is enabled"""
        return (
            hasattr(settings, 'WITHINGS_WEBHOOK_SECRET') or
            hasattr(settings, 'SOCIAL_AUTH_FITBIT_SECRET') or
            getattr(settings, 'WEBHOOK_SIGNATURE_VALIDATION_ENABLED', True)
        )

    def get_validation_config(self) -> dict:
        """Get current webhook validation configuration"""
        return {
            'withings_secret_configured': bool(getattr(settings, 'WITHINGS_WEBHOOK_SECRET', None)),
            'fitbit_secret_configured': bool(getattr(settings, 'SOCIAL_AUTH_FITBIT_SECRET', None)),
            'validation_enabled': self.is_signature_validation_enabled(),
            'supported_algorithms': ['sha256', 'sha1', 'md5']
        }