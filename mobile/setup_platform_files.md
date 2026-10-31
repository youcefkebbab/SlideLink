# One-time developer setup (needed only to BUILD the app, not to use it)

    flutter create --org com.slidelink --project-name slidelink --platforms=android,ios .
    flutter pub get

## Android – add to android/app/src/main/AndroidManifest.xml (inside <manifest>)
    <uses-permission android:name="android.permission.BLUETOOTH_SCAN" android:usesPermissionFlags="neverForLocation"/>
    <uses-permission android:name="android.permission.BLUETOOTH_CONNECT"/>
    <uses-permission android:name="android.permission.BLUETOOTH" android:maxSdkVersion="30"/>
    <uses-permission android:name="android.permission.BLUETOOTH_ADMIN" android:maxSdkVersion="30"/>
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="30"/>
    <uses-feature android:name="android.hardware.bluetooth_le" android:required="true"/>
In android/app/build.gradle(.kts) set minSdk to 23 (flutter_secure_storage needs 23).

## iOS – add to ios/Runner/Info.plist
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>SlideLink uses Bluetooth to control your presentation on your computer.</string>
Set the iOS deployment target to 13.0 or higher.

## Build
    flutter build apk --release        # -> build/app/outputs/flutter-apk/app-release.apk
    flutter run --release              # iPhone connected to a Mac (Xcode signing with your Apple ID)
