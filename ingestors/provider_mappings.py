"""
Provider Data Type Mappings - Single Source of Truth

This module provides a centralized, comprehensive mapping between:
1. User-configured data types (business logic)
2. Provider-specific subscription categories (webhook subscriptions)
3. Provider-specific API endpoints and parameters (data fetching)
4. Provider-specific meastypes (for Withings /v2/measure endpoint)

Architecture:
    User Config → Data Type Config → Subscription Categories + API Details

Example Flow:
    User wants: ['ecg', 'heart_rate', 'weight']
    System resolves: Subscribe to appli [1, 4, 54]
    When webhook arrives for appli 54: Fetch data using /v2/heart endpoint
"""
from dataclasses import dataclass
from typing import Optional, Union, List, Dict
from enum import Enum

from .health_data_constants import Provider


class APIMethod(Enum):
    """API request methods"""
    GET = "GET"
    POST = "POST"


@dataclass(frozen=True)
class DataTypeConfig:
    """
    Complete configuration for a single data type on a specific provider

    Attributes:
        name: Data type identifier (e.g., 'ecg', 'heart_rate')
        display_name: Human-readable name
        subscription_categories: List of provider-specific categories to subscribe to
            - Withings: appli types (e.g., ['54'] for ECG)
            - Fitbit: collection types (e.g., ['activities'] for heart rate)
        api_endpoint: API endpoint path for fetching this data
        api_method: HTTP method (GET or POST)
        api_action: Action parameter (e.g., 'list', 'getmeas')
        meastype: Withings-specific meastype(s) for /v2/measure endpoint
            - Can be int, list of ints, or None
            - Only used for /v2/measure endpoint
        response_processor: Method name to process API response
        requires_date_range: Whether this data type requires date range parameters
        description: Brief description of what this data type represents
    """
    name: str
    display_name: str
    subscription_categories: List[str]
    api_endpoint: str
    api_method: APIMethod
    api_action: Optional[str]
    meastype: Optional[Union[int, List[int]]]
    response_processor: str
    requires_date_range: bool
    description: str


# ==============================================================================
# WITHINGS DATA TYPE MAPPINGS
# ==============================================================================

WITHINGS_DATA_TYPES: Dict[str, DataTypeConfig] = {
    'ecg': DataTypeConfig(
        name='ecg',
        display_name='Electrocardiogram (ECG)',
        subscription_categories=['54'],  # Appli 54: ECG data
        api_endpoint='/v2/heart',
        api_method=APIMethod.GET,
        api_action='list',
        meastype=None,  # ECG uses Heart v2 API, not measure endpoint
        response_processor='_process_withings_ecg',
        requires_date_range=True,
        description='ECG recordings with AFib detection and heart rate'
    ),

    'heart_rate': DataTypeConfig(
        name='heart_rate',
        display_name='Heart Rate',
        subscription_categories=['4'],  # Appli 4: Pressure-related data
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=11,  # Meastype 11: Heart pulse
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Heart rate measurements in beats per minute'
    ),

    'weight': DataTypeConfig(
        name='weight',
        display_name='Weight',
        subscription_categories=['1'],  # Appli 1: Weight-related metrics
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=1,  # Meastype 1: Weight
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Body weight measurements in kg'
    ),

    'fat_mass': DataTypeConfig(
        name='fat_mass',
        display_name='Fat Mass',
        subscription_categories=['1'],  # Appli 1: Weight-related metrics
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=8,  # Meastype 8: Fat mass weight
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Body fat mass in kg'
    ),

    'steps': DataTypeConfig(
        name='steps',
        display_name='Steps',
        subscription_categories=['16'],  # Appli 16: Activity data
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getactivity',
        meastype=None,  # Activity uses different action, not meastype
        response_processor='_process_withings_activity',
        requires_date_range=True,
        description='Daily step count'
    ),

    'blood_pressure': DataTypeConfig(
        name='blood_pressure',
        display_name='Blood Pressure',
        subscription_categories=['4'],  # Appli 4: Pressure-related data
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=[9, 10],  # Meastype 9: Diastolic, 10: Systolic
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Blood pressure readings (systolic/diastolic)'
    ),

    'temperature': DataTypeConfig(
        name='temperature',
        display_name='Body Temperature',
        subscription_categories=['2'],  # Appli 2: Temperature-related data
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=12,  # Meastype 12: Temperature
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Body temperature measurements'
    ),

    'spo2': DataTypeConfig(
        name='spo2',
        display_name='Oxygen Saturation (SpO2)',
        subscription_categories=['4'],  # Appli 4: Pressure-related data
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=54,  # Meastype 54: SpO2
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Blood oxygen saturation percentage'
    ),

    'sleep': DataTypeConfig(
        name='sleep',
        display_name='Sleep Data',
        subscription_categories=['44'],  # Appli 44: Sleep-related data
        api_endpoint='/v2/sleep',
        api_method=APIMethod.GET,
        api_action='get',
        meastype=None,  # Sleep uses different endpoint
        response_processor='_process_withings_sleep',
        requires_date_range=True,
        description='Sleep sessions with stages and quality metrics'
    ),

    'rr_intervals': DataTypeConfig(
        name='rr_intervals',
        display_name='RR Intervals (HRV)',
        subscription_categories=['44'],  # Appli 44: Sleep-related data (includes HRV)
        api_endpoint='/v2/sleep',
        api_method=APIMethod.GET,
        api_action='get',
        meastype=None,
        response_processor='_process_withings_sleep',
        requires_date_range=True,
        description='Heart rate variability measurements'
    ),

    'glucose': DataTypeConfig(
        name='glucose',
        display_name='Blood Glucose',
        subscription_categories=['58'],  # Appli 58: Glucose data
        api_endpoint='/v2/measure',
        api_method=APIMethod.GET,
        api_action='getmeas',
        meastype=None,  # Glucose meastype TBD - not documented yet
        response_processor='_process_withings_measurements',
        requires_date_range=True,
        description='Blood glucose measurements'
    ),
}


# ==============================================================================
# FITBIT DATA TYPE MAPPINGS
# ==============================================================================

FITBIT_DATA_TYPES: Dict[str, DataTypeConfig] = {
    'heart_rate': DataTypeConfig(
        name='heart_rate',
        display_name='Heart Rate',
        subscription_categories=['activities'],  # Fitbit collection type
        api_endpoint='/1/user/-/activities/heart/date/{date}/1d.json',
        api_method=APIMethod.GET,
        api_action=None,
        meastype=None,  # Fitbit doesn't use meastypes
        response_processor='_process_fitbit_heart_rate',
        requires_date_range=True,
        description='Heart rate zones and intraday measurements'
    ),

    'steps': DataTypeConfig(
        name='steps',
        display_name='Steps',
        subscription_categories=['activities'],
        api_endpoint='/1/user/-/activities/steps/date/{date}/1d.json',
        api_method=APIMethod.GET,
        api_action=None,
        meastype=None,
        response_processor='_process_fitbit_activity',
        requires_date_range=True,
        description='Daily step count and intraday data'
    ),

    'weight': DataTypeConfig(
        name='weight',
        display_name='Weight',
        subscription_categories=['body'],
        api_endpoint='/1/user/-/body/log/weight/date/{date}.json',
        api_method=APIMethod.GET,
        api_action=None,
        meastype=None,
        response_processor='_process_fitbit_weight',
        requires_date_range=True,
        description='Body weight logs'
    ),

    'sleep': DataTypeConfig(
        name='sleep',
        display_name='Sleep Data',
        subscription_categories=['sleep'],
        api_endpoint='/1.2/user/-/sleep/date/{date}.json',
        api_method=APIMethod.GET,
        api_action=None,
        meastype=None,
        response_processor='_process_fitbit_sleep',
        requires_date_range=True,
        description='Sleep stages and quality metrics'
    ),

    'ecg': DataTypeConfig(
        name='ecg',
        display_name='Electrocardiogram (ECG)',
        subscription_categories=['activities'],  # ECG notifications come through activities
        api_endpoint='/1/user/-/ecg/list.json',
        api_method=APIMethod.GET,
        api_action=None,
        meastype=None,
        response_processor='_process_fitbit_ecg',
        requires_date_range=True,
        description='ECG readings with AFib detection'
    ),

    'rr_intervals': DataTypeConfig(
        name='rr_intervals',
        display_name='HRV (RR Intervals)',
        subscription_categories=['activities'],
        api_endpoint='/1/user/-/hrv/date/{date}/all.json',
        api_method=APIMethod.GET,
        api_action=None,
        meastype=None,
        response_processor='_process_fitbit_hrv',
        requires_date_range=True,
        description='Heart rate variability measurements'
    ),
}


# ==============================================================================
# COMBINED PROVIDER MAPPINGS
# ==============================================================================

PROVIDER_DATA_TYPE_MAPPINGS: Dict[Provider, Dict[str, DataTypeConfig]] = {
    Provider.WITHINGS: WITHINGS_DATA_TYPES,
    Provider.FITBIT: FITBIT_DATA_TYPES,
}


# ==============================================================================
# REVERSE MAPPINGS: SUBSCRIPTION CATEGORY → DATA TYPES
# ==============================================================================

def get_category_to_data_types_mapping(provider: Provider) -> Dict[str, List[str]]:
    """
    Build reverse mapping from subscription categories to data types

    This is used by webhook processors to determine which data types
    to fetch when receiving a notification for a specific category.

    Example for Withings:
        {
            '1': ['weight', 'fat_mass'],
            '4': ['heart_rate', 'blood_pressure', 'spo2'],
            '54': ['ecg'],
            ...
        }
    """
    category_mapping: Dict[str, List[str]] = {}

    data_types = PROVIDER_DATA_TYPE_MAPPINGS.get(provider, {})
    for data_type_name, config in data_types.items():
        for category in config.subscription_categories:
            if category not in category_mapping:
                category_mapping[category] = []
            category_mapping[category].append(data_type_name)

    return category_mapping


def resolve_subscription_categories(provider: Provider, data_types: List[str]) -> List[str]:
    """
    Resolve which subscription categories are needed for requested data types

    Args:
        provider: The health data provider
        data_types: List of user-requested data type names

    Returns:
        List of unique subscription categories to subscribe to

    Example:
        Input: provider=WITHINGS, data_types=['ecg', 'heart_rate', 'weight']
        Output: ['1', '4', '54']
    """
    categories = set()
    provider_mappings = PROVIDER_DATA_TYPE_MAPPINGS.get(provider, {})

    for data_type in data_types:
        if data_type in provider_mappings:
            categories.update(provider_mappings[data_type].subscription_categories)

    return sorted(list(categories))


def get_data_type_config(provider: Provider, data_type: str) -> Optional[DataTypeConfig]:
    """
    Get configuration for a specific data type on a provider

    Returns None if the data type is not supported by the provider
    """
    return PROVIDER_DATA_TYPE_MAPPINGS.get(provider, {}).get(data_type)


def get_supported_data_types(provider: Provider) -> List[str]:
    """Get list of all supported data types for a provider"""
    return list(PROVIDER_DATA_TYPE_MAPPINGS.get(provider, {}).keys())


def validate_data_types(provider: Provider, data_types: List[str]) -> tuple[List[str], List[str]]:
    """
    Validate which data types are supported by the provider

    Returns:
        Tuple of (supported_types, unsupported_types)
    """
    supported = []
    unsupported = []
    provider_mappings = PROVIDER_DATA_TYPE_MAPPINGS.get(provider, {})

    for data_type in data_types:
        if data_type in provider_mappings:
            supported.append(data_type)
        else:
            unsupported.append(data_type)

    return (supported, unsupported)
