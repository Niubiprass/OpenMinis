import Foundation
import KWWKAI

/// A per-request transport: no cookies, credential cache, cross-host redirects
/// or raw request/error logging. The consumer owns the socket for its whole life.
final class SubscriptionHTTPClient: KWWKAI.HTTPClient, @unchecked Sendable {
    let allowedHosts: Set<String>
    let timeout: TimeInterval
    let maxResponseBytes: Int

    init(allowedHosts: Set<String>, timeout: TimeInterval = 60,
         maxResponseBytes: Int = 64 * 1024 * 1024) {
        self.allowedHosts = Set(allowedHosts.map { $0.lowercased() })
        self.timeout = timeout
        self.maxResponseBytes = maxResponseBytes
    }

    func stream(url: URL, method: String, headers: [String: String], body: Data?,
                cancellation: KWWKAI.CancellationHandle?) async throws
        -> (HTTPURLResponse, AsyncThrowingStream<Data, Error>) {
        try await stream(url: url, method: method, headers: headers, body: body,
                         cancellation: cancellation, timeoutSeconds: timeout)
    }

    func stream(url: URL, method: String, headers: [String: String], body: Data?,
                cancellation: KWWKAI.CancellationHandle?, timeoutSeconds: TimeInterval) async throws
        -> (HTTPURLResponse, AsyncThrowingStream<Data, Error>) {
        guard url.scheme?.lowercased() == "https", let host = url.host?.lowercased(),
              allowedHosts.contains(host), url.user == nil, url.password == nil,
              url.port == nil || url.port == 443 else {
            throw SubscriptionProviderError.invalidResponse("请求地址不属于此服务商，已阻止发送登录信息")
        }
        try Task.checkCancellation()
        try cancellation?.throwIfCancelled()
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = max(1, min(timeoutSeconds, timeout))
        for (k, v) in headers { request.setValue(v, forHTTPHeaderField: k) }
        let transport = SubscriptionHTTPStream(limit: maxResponseBytes)
        let bytes = transport.makeBodyStream()
        let registration = cancellation?.onCancel { _ in transport.cancel() }
        transport.setCancellationRegistration(registration)
        do {
            let response = try await withTaskCancellationHandler {
                try await transport.start(request)
            } onCancel: { transport.cancel() }
            return (response, bytes)
        } catch {
            transport.cancel()
            throw error
        }
    }
}

private final class SubscriptionHTTPStream: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private let limit: Int
    private var size = 0
    private var ended = false
    private var header: CheckedContinuation<HTTPURLResponse, Error>?
    private var body: AsyncThrowingStream<Data, Error>.Continuation?
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var cancelRegistration: KWWKAI.CancellationRegistration?

    init(limit: Int) { self.limit = limit; super.init() }

    func setCancellationRegistration(_ registration: KWWKAI.CancellationRegistration?) {
        let completed = lock.subscriptionWithLock { () -> Bool in
            guard !ended else { return true }
            cancelRegistration = registration
            return false
        }
        if completed { registration?.cancel() }
    }

    func makeBodyStream() -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream(bufferingPolicy: .bufferingOldest(128)) { continuation in
            lock.subscriptionWithLock { body = continuation }
            continuation.onTermination = { [weak self] _ in self?.cancel() }
        }
    }

    func start(_ request: URLRequest) async throws -> HTTPURLResponse {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            if ended || Task.isCancelled {
                lock.unlock()
                continuation.resume(throwing: CancellationError())
                return
            }
            let config = URLSessionConfiguration.ephemeral
            config.httpCookieStorage = nil
            config.urlCredentialStorage = nil
            config.urlCache = nil
            config.httpShouldSetCookies = false
            config.requestCachePolicy = .reloadIgnoringLocalCacheData
            config.timeoutIntervalForRequest = request.timeoutInterval
            config.timeoutIntervalForResource = 1200
            let queue = OperationQueue()
            queue.maxConcurrentOperationCount = 1
            let session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
            let task = session.dataTask(with: request)
            self.session = session
            self.task = task
            self.header = continuation
            lock.unlock()
            task.resume()
        }
    }

    func cancel() { finish(CancellationError(), cancelTask: true) }

    private func finish(_ error: Error?, cancelTask: Bool) {
        let state = lock.subscriptionWithLock { () -> (
            CheckedContinuation<HTTPURLResponse, Error>?,
            AsyncThrowingStream<Data, Error>.Continuation?, URLSessionDataTask?, URLSession?,
            KWWKAI.CancellationRegistration?)? in
            guard !ended else { return nil }
            ended = true
            let state = (header, body, task, session, cancelRegistration)
            header = nil; body = nil; task = nil; session = nil; cancelRegistration = nil
            return state
        }
        guard let state else { return }
        state.0?.resume(throwing: error ?? URLError(.badServerResponse))
        if let error { state.1?.finish(throwing: error) } else { state.1?.finish() }
        state.4?.cancel()
        if cancelTask { state.2?.cancel(); state.3?.invalidateAndCancel() }
        else { state.3?.finishTasksAndInvalidate() }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil) // Never forward an account token to a redirect target.
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let http = response as? HTTPURLResponse,
              http.expectedContentLength <= Int64(limit) else {
            completionHandler(.cancel)
            finish(URLError(.dataLengthExceedsMaximum), cancelTask: true)
            return
        }
        let continuation = lock.subscriptionWithLock { () -> CheckedContinuation<HTTPURLResponse, Error>? in
            let old = header; header = nil; return old
        }
        continuation?.resume(returning: http)
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        let state = lock.subscriptionWithLock { () -> (Bool, AsyncThrowingStream<Data, Error>.Continuation?) in
            size += data.count
            return (size > limit, body)
        }
        if state.0 { finish(URLError(.dataLengthExceedsMaximum), cancelTask: true); return }
        if let continuation = state.1, case .dropped = continuation.yield(data) {
            finish(SubscriptionProviderError.invalidResponse("回复积压过大，已停止请求"), cancelTask: true)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        finish(error, cancelTask: false)
    }
}
