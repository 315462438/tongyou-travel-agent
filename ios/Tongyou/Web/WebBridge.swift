import Foundation

/// Script injected into the web fallback (features not yet native, such as editing a trip):
/// - shares the native session token with the web app;
/// - forwards blob/data downloads and window.print(), which WKWebView ignores, to native code.
enum WebBridge {
    static let handler = "tongyou"
    static let host = "17tongyou.com"

    static let script = #"""
    (() => {
      if (window.__tongyouBridge) return;
      window.__tongyouBridge = true;
      const post = (message) => { try { window.webkit.messageHandlers.tongyou.postMessage(message); } catch (_) {} };
      // Signed in natively: hand the same session token to the web app (its authFetch reads localStorage).
      if (location.hostname.endsWith('17tongyou.com') && __TOKEN__) {
        try { localStorage.setItem('travel_token', __TOKEN__); } catch (_) {}
      }

      // The site revokes object URLs right after a.click(); keep them alive long enough to read.
      const revoke = URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL = (url) => setTimeout(() => revoke(url), 60000);
      const save = (href, name) => fetch(href)
        .then((r) => r.blob())
        .then((blob) => new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve({ blob, data: String(reader.result) });
          reader.onerror = () => reject(reader.error);
          reader.readAsDataURL(blob);
        }))
        .then(({ blob, data }) => post({ type: 'download', name: name || 'download', mime: blob.type || '', data }))
        .catch((error) => post({ type: 'downloadError', message: String(error) }));
      const isLocal = (a) => a.hasAttribute('download') && /^(blob|data):/.test(a.href);
      const click = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () {
        if (isLocal(this)) { save(this.href, this.getAttribute('download')); return; }
        return click.call(this);
      };
      document.addEventListener('click', (event) => {
        const a = event.target && event.target.closest && event.target.closest('a[download]');
        if (a && isLocal(a)) { event.preventDefault(); save(a.href, a.getAttribute('download')); }
      }, true);
      window.print = () => post({ type: 'print', title: document.title });

    })();
    """#

    static func source(token: String?) -> String {
        let quoted = (try? String(data: JSONSerialization.data(withJSONObject: [token ?? ""]), encoding: .utf8))
            .map { String($0.dropFirst().dropLast()) } ?? "\"\""
        return script.replacingOccurrences(of: "__TOKEN__", with: quoted)
    }
}
