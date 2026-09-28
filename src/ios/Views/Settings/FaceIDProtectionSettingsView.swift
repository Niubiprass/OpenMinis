//
//  FaceIDProtectionSettingsView.swift
//  MinisApp
//
//  Settings entry for per-session biometric protection. Surfaces the
//  master toggle, an idle-timeout picker, and (when relevant) a count of
//  currently-locked sessions with a "clear all" affordance.
//
//  Hidden in the parent settings list when the device lacks biometric
//  capability — see `BiometricAuth.isAvailable`.
//

import SwiftUI

struct FaceIDProtectionSettingsView: View {
    @ObservedObject private var store = SessionLockStore.shared
    @AppStorage(SessionLockDefaultsKey.enabled) private var enabled: Bool = false
    @AppStorage(SessionLockDefaultsKey.idleSeconds) private var idleSeconds: Int = 300
    @AppStorage(SessionLockDefaultsKey.appLockEnabled) private var appLockEnabled: Bool = false
    @AppStorage(SessionLockDefaultsKey.appLockIdleSeconds) private var appLockIdleSeconds: Int = -1

    var body: some View {
        Form {
            // MARK: - App Lock
            Section {

            if appLockEnabled {
                Section {
                    Text("How long after leaving the app before the lock re-engages.")
                }
            }

            // MARK: - Per-Session Lock
            Section {

            if enabled {
                Section {
                    Text("After leaving an unlocked session, the lock re-engages once the idle window elapses.")
                }

                Section {
                    HStack {
                        Text("Locked sessions")
                        Spacer()
                        Text("\(store.lockedSessionIds.count)")
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                    if !store.lockedSessionIds.isEmpty {
                        Button(role: .destructive) {
                    }
                }
            }
        }
        .navigationTitle("\(BiometricAuth.biometryDisplayName) Protection")
        .navigationBarTitleDisplayMode(.inline)
    }
}
