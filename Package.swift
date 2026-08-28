// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "ext4-crash-poc",
    platforms: [.macOS("15.0")],
    dependencies: [
        // Pin this to the commit/tag you're validating the report against.
        .package(url: "https://github.com/apple/containerization.git", branch: "main"),
        .package(url: "https://github.com/apple/swift-system.git", from: "1.6.4"),
    ],
    targets: [
        .executableTarget(
            name: "ext4-crash-poc",
            dependencies: [
                .product(name: "ContainerizationEXT4", package: "containerization"),
                .product(name: "SystemPackage", package: "swift-system"),
            ]
        )
    ]
)
