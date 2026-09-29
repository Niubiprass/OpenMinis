import Foundation
import SwiftUI
import UIKit
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
/// Presents view controllers directly on the top-most UIKit view controller,
/// bypassing SwiftUI's presentation system entirely.
///
/// Why: AIChatView's body chain carries 15+ `.sheet` modifiers plus a
/// `.fileImporter`. iOS 16+ tolerates that; **iOS 15's SwiftUI silently drops
/// presentations** when many `.sheet(isPresented:)` modifiers share one view
/// chain — the camera still works because it uses `.fullScreenCover`, while
/// the photo picker sheet and the document fileImporter never appear.
/// Presenting through UIKit sidesteps every one of those quirks.
enum UIKitPickerPresenter {
    static func present(_ vc: UIViewController) {
        // Let a dismissing confirmationDialog finish its animation first;
        // presenting while another dismissal is in flight gets dropped.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard var top = scenes.flatMap({ $0.windows }).first(where: { $0.isKeyWindow })?.rootViewController else {
                return
            }
            while let presented = top.presentedViewController, !presented.isBeingDismissed {
                top = presented
            }
            top.present(vc, animated: true)
        }
    }
}

/// Retained delegate for the UIKit photo & document pickers. Held as `@State`
/// on AIChatView so it lives as long as the view; closures are assigned at
/// presentation time to capture the current view model.
final class AttachmentPickerCoordinator: NSObject, PHPickerViewControllerDelegate, UIDocumentPickerViewControllerDelegate {
    var onPhotos: (([PHPickerResult]) -> Void)?
    var onFiles: (([URL]) -> Void)?

    func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        picker.dismiss(animated: true)
        onPhotos?(results)
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        // `asCopy: true` pickers hand out plain temp-file copies — no security
        // scope needed (addFileAttachment's scope calls are harmless no-ops).
        onFiles?(urls)
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {}
}

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
