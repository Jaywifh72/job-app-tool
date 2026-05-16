#!/bin/bash
echo "Downloading Gradle Wrapper..."
curl -sL -o gradle/wrapper/gradle-wrapper.jar \
  https://github.com/gradle/gradle/raw/v8.9.0/gradle/wrapper/gradle-wrapper.jar
echo "Building APK..."
chmod +x gradlew
./gradlew assembleRelease --no-daemon
