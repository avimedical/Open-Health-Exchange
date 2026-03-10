# Mobile App Deeplink Integration

This guide explains how to integrate mobile apps with the Open Health Exchange OAuth flow using deeplinks.

## Overview

The OAuth flow supports custom deeplink URLs that redirect users back to your mobile app after successful or failed provider linking. This provides a seamless experience for mobile users without requiring them to manually copy tokens or navigate back to the app.

## Configuration

### Method 1: Provider-Level Configuration (Recommended)

Configure deeplink URLs in the Django Admin for each provider:

1. Navigate to Django Admin → Providers
2. Edit the provider (e.g., Withings)
3. Expand "Mobile App Integration" section
4. Set the deeplink URLs:
   - **Success Deeplink URL**: `myapp://oauth/success/withings/`
   - **Error Deeplink URL**: `myapp://oauth/error/withings/`

These URLs will be used for all OAuth flows for that provider unless overridden per-request.

### Method 2: Per-Request Configuration

Override deeplink URLs on a per-request basis using query parameters:

```
GET /api/base/link/{provider}/?ehr_user_id=123&success_url=myapp://success&error_url=myapp://error
```

This is useful when:
- Different apps use the same provider configuration
- You need dynamic deeplink URLs based on user context
- Testing different deeplink schemes

## OAuth Flow

### 1. Initiate OAuth Flow

Mobile app opens browser/webview with:

```
https://your-server.com/api/base/link/withings/?ehr_user_id=USER_ID&success_url=myapp://oauth/success&error_url=myapp://oauth/error
```

Query parameters:
- `ehr_user_id` (required): EHR user identifier
- `success_url` (optional): Custom success deeplink
- `error_url` (optional): Custom error deeplink

### 2. User Completes OAuth

User authenticates with the provider (Withings, Fitbit, etc.) and grants permissions.

### 3. Redirect to Mobile App

**On Success:**
```
myapp://oauth/success/withings/?provider=withings&ehr_user_id=USER_ID&status=success
```

**On Error:**
```
myapp://oauth/error/withings/?provider=withings&ehr_user_id=USER_ID&status=error&error=access_denied&message=User+denied+access
```

## Mobile App Implementation

### iOS (Swift)

#### 1. Register URL Scheme

In `Info.plist`:

```xml
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>myapp</string>
        </array>
        <key>CFBundleURLName</key>
        <string>com.example.myapp</string>
    </dict>
</array>
```

#### 2. Handle Deeplink

```swift
import UIKit

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        guard let url = URLContexts.first?.url else { return }

        // Parse URL components
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let queryItems = components?.queryItems ?? []

        // Extract parameters
        let provider = queryItems.first(where: { $0.name == "provider" })?.value
        let status = queryItems.first(where: { $0.name == "status" })?.value
        let ehrUserId = queryItems.first(where: { $0.name == "ehr_user_id" })?.value

        if status == "success" {
            // Handle successful OAuth
            print("Successfully linked \(provider ?? "unknown") for user \(ehrUserId ?? "unknown")")
            showSuccessScreen(provider: provider)
        } else if status == "error" {
            // Handle OAuth error
            let error = queryItems.first(where: { $0.name == "error" })?.value
            let message = queryItems.first(where: { $0.name == "message" })?.value
            print("OAuth error: \(error ?? "unknown") - \(message ?? "unknown")")
            showErrorScreen(error: error, message: message)
        }
    }
}
```

### Android (Kotlin)

#### 1. Register Intent Filter

In `AndroidManifest.xml`:

```xml
<activity android:name=".OAuthCallbackActivity">
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data
            android:scheme="myapp"
            android:host="oauth" />
    </intent-filter>
</activity>
```

#### 2. Handle Deeplink

```kotlin
class OAuthCallbackActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val data = intent.data
        if (data != null) {
            val provider = data.getQueryParameter("provider")
            val status = data.getQueryParameter("status")
            val ehrUserId = data.getQueryParameter("ehr_user_id")

            when (status) {
                "success" -> {
                    // Handle successful OAuth
                    Log.d("OAuth", "Successfully linked $provider for user $ehrUserId")
                    showSuccessScreen(provider)
                }
                "error" -> {
                    // Handle OAuth error
                    val error = data.getQueryParameter("error")
                    val message = data.getQueryParameter("message")
                    Log.e("OAuth", "OAuth error: $error - $message")
                    showErrorScreen(error, message)
                }
            }
        }
    }
}
```

### React Native

#### 1. Install Linking Module

```bash
npm install react-native-linking
```

#### 2. Configure Deeplinks

**iOS**: Update `Info.plist` (see iOS example above)

**Android**: Update `AndroidManifest.xml` (see Android example above)

#### 3. Handle Deeplink

```javascript
import { useEffect } from 'react';
import { Linking } from 'react-native';

function App() {
  useEffect(() => {
    // Handle initial URL if app was closed
    Linking.getInitialURL().then(url => {
      if (url) {
        handleDeepLink(url);
      }
    });

    // Handle deep links when app is running
    const subscription = Linking.addEventListener('url', ({ url }) => {
      handleDeepLink(url);
    });

    return () => {
      subscription.remove();
    };
  }, []);

  const handleDeepLink = (url) => {
    const { queryParams } = Linking.parse(url);
    const { provider, status, ehr_user_id, error, message } = queryParams;

    if (status === 'success') {
      console.log(`Successfully linked ${provider} for user ${ehr_user_id}`);
      navigation.navigate('OAuthSuccess', { provider });
    } else if (status === 'error') {
      console.log(`OAuth error: ${error} - ${message}`);
      navigation.navigate('OAuthError', { error, message });
    }
  };

  // ... rest of app
}
```

## Query Parameters Reference

### Success Deeplink

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | string | Provider name (withings, fitbit) |
| `ehr_user_id` | string | EHR user identifier |
| `status` | string | Always "success" |

### Error Deeplink

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | string | Provider name (withings, fitbit) |
| `ehr_user_id` | string | EHR user identifier |
| `status` | string | Always "error" |
| `error` | string | Error code (e.g., "access_denied", "invalid_request") |
| `message` | string | Human-readable error message |

## Common Error Codes

| Error Code | Description |
|------------|-------------|
| `access_denied` | User denied authorization |
| `invalid_request` | Malformed OAuth request |
| `unauthorized_client` | Client not authorized |
| `server_error` | OAuth provider error |
| `temporarily_unavailable` | Provider service unavailable |

## Testing

### Test Deeplinks Locally

1. Configure test deeplink URLs in Django Admin
2. Use a tool like [deeplink.me](https://deeplink.me) to test iOS/Android deeplinks
3. Monitor Django logs to see redirect URLs:
   ```
   INFO ... Redirecting to mobile app success deeplink: myapp://oauth/success/withings/?...
   ```

### Test Without Mobile App

Use a web-based deeplink testing tool:

1. Set success URL to: `https://deeplink-tester.com/success`
2. Complete OAuth flow
3. See redirect parameters in browser

## Security Considerations

1. **Validate Deeplinks**: Always validate that deeplink URLs match your app's registered URL scheme
2. **State Parameter**: The OAuth flow includes state validation to prevent CSRF attacks
3. **HTTPS Only**: OAuth initiation should always use HTTPS
4. **Token Storage**: Never expose tokens in deeplink URLs (they're stored server-side)

## Fallback Behavior

If no deeplink URLs are configured:
- Success: Shows default web success page at `/complete/oauth/success/`
- Error: Shows default web error page at `/complete/oauth/error/`

This ensures backward compatibility with existing integrations.

## Example: Complete Mobile Flow

```javascript
// 1. Mobile app initiates OAuth
const oauthUrl = `https://api.example.com/api/base/link/withings/?` +
  `ehr_user_id=${userId}&` +
  `success_url=myapp://oauth/success&` +
  `error_url=myapp://oauth/error`;

// Open in system browser or in-app browser
Linking.openURL(oauthUrl);

// 2. User completes OAuth in browser

// 3. System redirects back to app via deeplink
// myapp://oauth/success?provider=withings&ehr_user_id=123&status=success

// 4. App handles deeplink (see React Native example above)

// 5. App shows success screen and syncs data
await syncHealthData(provider, userId);
```

## Troubleshooting

### Deeplink Not Redirecting

1. Verify URL scheme is registered in app configuration
2. Check Django logs for actual redirect URL
3. Test deeplink manually using `adb` (Android) or simulator (iOS)

### Parameters Not Received

1. URL might be encoded - ensure proper URL parsing
2. Check that query parameters are preserved through redirect
3. Verify deeplink URL doesn't strip query params

### Works in Browser, Not in App

1. Ensure app is installed and URL scheme registered
2. Test with a simple deeplink first (e.g., `myapp://test`)
3. Check platform-specific deeplink handling (iOS Universal Links, Android App Links)
