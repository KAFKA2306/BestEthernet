plugins {
    id("com.android.application")
}

android {
    namespace = "io.github.kafka2306.zerotrustdns"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.github.kafka2306.zerotrustdns"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "0.1.0"
    }

    buildFeatures {
        buildConfig = false
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += setOf("META-INF/DEPENDENCIES", "META-INF/LICENSE*", "META-INF/NOTICE*")
    }
}
