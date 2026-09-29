import Foundation
import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

/// iOS 15-compatible photo + video picker.
///
/// The upstream build presented the picker with SwiftUI's
/// `.photosPicker(isPresented:selection:)` modifier, which is iOS 16+. The iOS-15
/// port stripped that modifier so the app would compile — with the side effect that
/// the "Choose Photos & Videos" button did nothing on iOS 15 (in fact on every
/// version of this ported build). `PHPickerViewController` has been available since
/// iOS 14, so this `UIViewControllerRepresentable` restores image/video picking
/// with zero iOS-16-only dependencies.
struct PHPickerView: UIViewControllerRepresentable {
    /// Called once the user finishes (or cancels) picking. Empty array = cancel.
    let onPicked: ([PHPickerResult]) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .any(of: [.images, .videos])
        config.selectionLimit = 0 // 0 = unlimited
        config.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onPicked: onPicked)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPicked: ([PHPickerResult]) -> Void
        init(onPicked: @escaping ([PHPickerResult]) -> Void) { self.onPicked = onPicked }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            onPicked(results)
        }
    }
}
