// Renders carousel/carousel.html#export with WebKit and writes one PDF page per slide.
// Usage: swift tools/export_pdf.swift <url> <out.pdf>
import AppKit
import PDFKit
import WebKit

let args = CommandLine.arguments
let url = URL(string: args.count > 1 ? args[1] : "http://localhost:8765/carousel.html#export")!
let out = URL(fileURLWithPath: args.count > 2 ? args[2] : "carousel/jev-inbox-test.pdf")
let slideW: CGFloat = 1080, slideH: CGFloat = 1350, slides = 10

final class Exporter: NSObject, WKNavigationDelegate {
    let web = WKWebView(frame: NSRect(x: 0, y: 0, width: slideW, height: slideH * CGFloat(slides)))
    let doc = PDFDocument()

    func start() { web.navigationDelegate = self; web.load(URLRequest(url: url)) }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // wait for web fonts before capturing
        web.evaluateJavaScript("document.fonts.ready.then(() => true)") { _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.capture(0) }
        }
    }

    func capture(_ i: Int) {
        guard i < slides else {
            doc.write(to: out); print("wrote \(out.path) (\(doc.pageCount) pages)"); exit(0)
        }
        let cfg = WKPDFConfiguration()
        cfg.rect = CGRect(x: 0, y: CGFloat(i) * slideH, width: slideW, height: slideH)
        web.createPDF(configuration: cfg) { result in
            guard case .success(let data) = result, let page = PDFDocument(data: data)?.page(at: 0) else {
                print("failed on slide \(i + 1)"); exit(1)
            }
            self.doc.insert(page, at: self.doc.pageCount)
            self.capture(i + 1)
        }
    }
}

let app = NSApplication.shared
let exporter = Exporter()
exporter.start()
app.run()
