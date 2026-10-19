import Foundation
import WebKit

/// [T-csp-recovery] Shared recovery for pages that download their scripts but
/// never run them.
///
/// The concrete case: linux.do serves Discourse with
/// `Content-Security-Policy: script-src 'nonce-…' 'strict-dynamic'` while the
/// HTML that reaches an iOS 15 WKWebView carries `nonce=""` on every script
/// tag. `strict-dynamic` still needs a trusted root, so nothing executes: the
/// framework global stays undefined and the splash spins forever. Safari and
/// every WKWebView on iOS 15 are hit; Gecko-based browsers are not.
///
/// `loadHTMLString` re-renders the SAME markup with no HTTP response, hence no
/// CSP header, so the scripts finally run. Cookies stay in
/// `WKWebsiteDataStore` and are still attached to the page's own XHR — only the
/// document source is swapped. Links, form posts and redirects remain real
/// navigations.
///
/// This helper is deliberately framework-agnostic: it looks for "scripts are
/// present but almost nothing is laid out", which covers Discourse, Vue,
/// React and plain JS sites alike. It is NOT applied to the automation browser
/// (BrowserUse), where re-rendering would discard the DOM state that tool
/// depends on.
enum CSPRecovery {

    /// Injected after `didFinish`. Returns `"stuck"` only when the page is
    /// visually empty yet carries a real script payload.
    ///
    /// Deliberately avoids measuring `innerText`: a stuck Discourse page still
    /// reports ~1.5 KB of hidden policy text, so text length is not a signal.
    /// Layout size is.
    static let probeScript = """
    (function(){
      var body = document.body;
      if (!body) return 'ok';
      var splash = document.getElementById('d-splash');
      if (splash && getComputedStyle(splash).display !== 'none'
          && typeof Discourse === 'undefined') return 'stuck';
      var scripts = document.getElementsByTagName('script').length;
      if (scripts < 5) return 'ok';
      if (document.images.length > 0) return 'ok';
      var nodes = body.querySelectorAll('div,main,section,article,nav,header');
      var visible = 0;
      for (var i = 0; i < nodes.length && i < 400; i++) {
        var r = nodes[i].getBoundingClientRect();
        if (r.width > 40 && r.height > 20) {
          visible++;
          if (visible > 8) return 'ok';
        }
      }
      return visible <= 2 ? 'stuck' : 'ok';
    })()
    """

    /// True when the probe says the page never laid itself out.
    static func isStuck(_ result: Any?) -> Bool {
        (result as? String) == "stuck"
    }

    /// Runs the probe and, when stuck, re-renders the page's own DOM through
    /// `loadHTMLString`. `alreadyRepaired` is a reference type owned by the
    /// caller: an `inout Set` cannot be captured by the escaping completion
    /// closures below, and Swift rejects overlapping access to a stored
    /// property captured that way.
    static func repairIfStuck(_ webView: WKWebView,
                              alreadyRepaired: NSMutableSet) {
        guard let url = webView.url,
              let scheme = url.scheme,
              scheme.hasPrefix("http") else { return }
        let key = url.absoluteString
        guard !alreadyRepaired.contains(key) else { return }

        webView.evaluateJavaScript(probeScript) { result, _ in
            guard isStuck(result) else { return }
            webView.evaluateJavaScript("document.documentElement.outerHTML") { html, _ in
                guard let html = html as? String, html.count > 1000 else { return }
                alreadyRepaired.add(key)
                webView.loadHTMLString("<!DOCTYPE html>" + html, baseURL: url)
            }
        }
    }
}
