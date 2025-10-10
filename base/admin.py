from django.contrib import admin
from django import forms
from django.utils.html import format_html
from django.core.exceptions import ValidationError

from base.models import EHRUser, Provider


class DataTypeCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """
    Custom widget for selecting data types to exclude with rich metadata display

    Shows each data type with:
    - Display name and description
    - Subscription categories (appli/collection types)
    - API endpoint information
    - Visual indication of included/excluded status
    """
    # Use Django's default templates - no custom templates needed

    def __init__(self, provider_type=None, *args, **kwargs):
        self.provider_type = provider_type
        super().__init__(*args, **kwargs)
        # Add custom CSS class for styling
        if 'class' in self.attrs:
            self.attrs['class'] += ' data-type-checkbox-list'
        else:
            self.attrs['class'] = 'data-type-checkbox-list'

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        """Override to use simple display names as labels"""
        option = super().create_option(name, value, label, selected, index, subindex, attrs)

        if value and self.provider_type:
            # Get display name for this data type
            from ingestors.provider_mappings import get_data_type_config, Provider as ProviderEnum

            try:
                provider_enum = ProviderEnum[self.provider_type.upper()]
                config = get_data_type_config(provider_enum, value)

                if config:
                    # Simple label - just the display name
                    option['label'] = config.display_name
            except (ValueError, AttributeError, KeyError):
                # Fallback to the value if config not found
                pass

        return option


class ProviderAdminForm(forms.ModelForm):
    """
    Custom form for Provider admin with enhanced data type selection
    """

    class Meta:
        model = Provider
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Only customize if we have an existing provider (need provider_type)
        if self.instance and self.instance.provider_type:
            from ingestors.provider_mappings import get_supported_data_types, Provider as ProviderEnum

            try:
                provider_enum = ProviderEnum[self.instance.provider_type.upper()]
                available_types = get_supported_data_types(provider_enum)

                # Create choices from available data types
                choices = [(dt, dt) for dt in sorted(available_types)]

                # Replace the default JSONField widget with our custom checkbox widget
                self.fields['excluded_data_types'] = forms.MultipleChoiceField(
                    choices=choices,
                    widget=DataTypeCheckboxSelectMultiple(provider_type=self.instance.provider_type),
                    required=False,
                    initial=self.instance.excluded_data_types if self.instance.pk else [],
                    help_text=(
                        'Select data types to EXCLUDE from synchronization. '
                        'By default, all available data types are included. '
                        'Unchecked items will be synchronized.'
                    ),
                    label='Excluded Data Types'
                )

                # Update help text for other fields
                self.fields['default_data_types'].help_text = (
                    'DEPRECATED: Leave empty to use provider defaults from provider_mappings.py. '
                    'Use "Excluded Data Types" field instead to customize.'
                )
                self.fields['default_data_types'].required = False
                self.fields['default_data_types'].widget = forms.HiddenInput()

            except (ValueError, AttributeError) as e:
                # If provider_type is invalid, fall back to default behavior
                pass
        else:
            # For new providers, show a message
            self.fields['excluded_data_types'].help_text = (
                'Save the provider first, then you can configure which data types to exclude.'
            )
            self.fields['excluded_data_types'].widget = forms.TextInput(attrs={
                'readonly': True,
                'placeholder': 'Save provider first to configure data types'
            })

    def clean_excluded_data_types(self):
        """Validate that excluded data types are valid for this provider"""
        excluded = self.cleaned_data.get('excluded_data_types', [])

        if not excluded:
            return []

        if not self.instance or not self.instance.provider_type:
            return excluded

        from ingestors.provider_mappings import validate_data_types, Provider as ProviderEnum

        try:
            provider_enum = ProviderEnum[self.instance.provider_type.upper()]
            valid, invalid = validate_data_types(provider_enum, excluded)

            if invalid:
                raise ValidationError(
                    f'Invalid data types for {self.instance.provider_type}: {", ".join(invalid)}. '
                    f'Valid options: {", ".join(valid)}'
                )

            return valid

        except (ValueError, KeyError) as e:
            raise ValidationError(f'Error validating data types: {str(e)}')
        except Exception as e:
            raise ValidationError(f'Unexpected error: {str(e)}')

    def clean(self):
        """Overall form validation with detailed error messages"""
        cleaned_data = super().clean()

        # Check if there are any errors so far
        if self.errors:
            error_messages = []
            for field, errors in self.errors.items():
                for error in errors:
                    error_messages.append(f"{field}: {error}")

            raise ValidationError(
                f"Please fix the following errors: {'; '.join(error_messages)}"
            )

        return cleaned_data


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    form = ProviderAdminForm

    list_display = ('name', 'provider_type', 'active', 'webhook_enabled', 'effective_data_types_count')
    list_filter = ('provider_type', 'active', 'webhook_enabled', 'supports_webhooks')
    search_fields = ('name',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'provider_type', 'active')
        }),
        ('Webhook Configuration', {
            'fields': ('supports_webhooks', 'webhook_enabled'),
            'description': 'Configure webhook support for real-time data synchronization'
        }),
        ('Mobile App Integration', {
            'fields': ('success_deeplink_url', 'error_deeplink_url'),
            'description': (
                'Optional deeplink URLs for mobile app OAuth redirects. '
                'If not set, users will see the default web success/error pages. '
                'Example: myapp://oauth/success/withings/ or myapp://oauth/error/fitbit/'
            ),
            'classes': ('collapse',)
        }),
        ('Data Type Configuration', {
            'fields': ('excluded_data_types', 'default_data_types'),
            'description': (
                'Configure which health data types to synchronize. '
                'By default, all available data types for this provider are included. '
                'Select data types below to exclude them from synchronization.'
            )
        }),
        ('Advanced', {
            'fields': ('credentials',),
            'classes': ('collapse',)
        })
    )

    readonly_fields = ('effective_data_types_summary',)

    def get_fieldsets(self, request, obj=None):
        """Add summary field after data type configuration for existing providers"""
        fieldsets = super().get_fieldsets(request, obj)

        if obj and obj.pk:
            # Create a deep copy to avoid mutating the original
            fieldsets = list(fieldsets)
            # Data Type Configuration is now at index 3 (after Mobile App Integration)
            data_type_section = list(fieldsets[3])
            data_type_section_dict = dict(data_type_section[1])

            # Only add if not already present
            current_fields = data_type_section_dict['fields']
            if 'effective_data_types_summary' not in current_fields:
                data_type_section_dict['fields'] = current_fields + ('effective_data_types_summary',)

            fieldsets[3] = (data_type_section[0], data_type_section_dict)
            fieldsets = tuple(fieldsets)

        return fieldsets

    def effective_data_types_count(self, obj):
        """Show count of effective data types in list view"""
        if not obj.pk:
            return '-'

        try:
            effective = obj.get_effective_data_types()
            return f"{len(effective)} active"
        except Exception:
            return 'Error'

    effective_data_types_count.short_description = 'Active Data Types'

    def effective_data_types_summary(self, obj):
        """Show detailed summary of effective data types"""
        if not obj.pk:
            return "Save provider to see effective data types"

        try:
            from ingestors.provider_mappings import get_data_type_config, Provider as ProviderEnum

            provider_enum = ProviderEnum[obj.provider_type.upper()]
            available = obj.get_available_data_types()
            excluded = obj.excluded_data_types
            effective = obj.get_effective_data_types()

            # Build HTML summary
            html_parts = [
                '<div style="margin: 10px 0; padding: 10px; background: #f8f9fa; border-left: 4px solid #28a745;">',
                f'<strong>✓ Active Data Types ({len(effective)}):</strong><br>',
            ]

            if effective:
                html_parts.append('<ul style="margin: 5px 0; padding-left: 20px;">')
                for dt_name in sorted(effective):
                    config = get_data_type_config(provider_enum, dt_name)
                    html_parts.append(
                        f'<li><strong>{config.display_name}</strong> '
                        f'<span style="color: #666;">({dt_name})</span> '
                        f'- {config.description}</li>'
                    )
                html_parts.append('</ul>')
            else:
                html_parts.append('<p style="color: #d9534f;">⚠ No data types will be synchronized!</p>')

            html_parts.append('</div>')

            if excluded:
                html_parts.append(
                    '<div style="margin: 10px 0; padding: 10px; background: #fff3cd; border-left: 4px solid #ffc107;">'
                )
                html_parts.append(f'<strong>✗ Excluded Data Types ({len(excluded)}):</strong><br>')
                html_parts.append('<ul style="margin: 5px 0; padding-left: 20px;">')
                for dt_name in sorted(excluded):
                    config = get_data_type_config(provider_enum, dt_name)
                    if config:
                        html_parts.append(
                            f'<li><strong>{config.display_name}</strong> '
                            f'<span style="color: #666;">({dt_name})</span></li>'
                        )
                html_parts.append('</ul>')
                html_parts.append('</div>')

            return format_html(''.join(html_parts))

        except Exception as e:
            return format_html('<p style="color: red;">Error: {}</p>', str(e))

    effective_data_types_summary.short_description = 'Synchronization Summary'


admin.site.register(EHRUser)
