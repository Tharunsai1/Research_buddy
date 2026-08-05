import type { NextConfig } from "next";

/** Where the FastAPI backend listens. Only this Next server ever connects to
 *  it, so it stays bound to loopback even when the app itself is reachable
 *  from an iPad on the network. */
const BACKEND = process.env.RC_BACKEND_ORIGIN ?? "http://127.0.0.1:8321";

const nextConfig: NextConfig = {
  /**
   * Serve the API from this same origin instead of calling the backend
   * directly. Three things fall out of that, all of which matter once the app
   * is opened from a tablet rather than from this machine:
   *
   *  - no CORS, because the browser sees a single origin;
   *  - no API address to configure, because a relative `/api/…` resolves
   *    against whatever host served the page — localhost here, a LAN address
   *    from the iPad — with nothing to rebuild when that address changes;
   *  - only port 3000 needs exposing to the network. The backend keeps
   *    listening on loopback, so nothing else can reach it directly.
   *
   * `:path*` covers multi-segment ids: pre-2007 arXiv papers really do look
   * like `quant-ph/9903061`, and a single-segment matcher would drop them.
   */
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },

  experimental: {
    /**
     * How long the rewrite above will wait for the backend. The default is 30
     * seconds, and almost nothing this app asks the backend for fits in 30
     * seconds: a literature matrix is one LLM call per paper, an appraisal is
     * five, and a deep read is more. Past the limit Next answers the browser
     * `500 Internal Server Error` with no body — while the backend carries on
     * and finishes normally, writing its cache.
     *
     * That failure is badly disguised. It looks like a backend crash, it is
     * indistinguishable from one in the UI, and retrying "fixes" it, because
     * by then the first request has completed and cached its result. It cost
     * two wrong diagnoses here: the same 500 was read as a per-paper
     * extraction bug in two different endpoints, both of which answer 200 when
     * called directly and only fail through the proxy.
     */
    proxyTimeout: 15 * 60 * 1000,
  },

  /**
   * Origins `next dev` will serve its dev runtime to. Without this the server
   * answers the HTML and the static chunks from any address, but refuses the
   * dev-only requests hydration depends on — so a tablet or phone gets a page
   * that renders correctly and then ignores every tap, with nothing in the UI
   * to say why. Reaching the app from another device is the documented setup
   * (see the LAN and iPad notes in the README), so those origins have to be
   * declared here or that path is broken by default.
   *
   * Dev-only; `next build`/`next start` ignore it. Private ranges and the
   * Tailscale namespace only — nothing routable from the public internet.
   */
  allowedDevOrigins: [
    "*.ts.net",       // Tailscale MagicDNS
    "100.*.*.*",      // Tailscale CGNAT range
    "192.168.*.*",    // home LAN
    "10.*.*.*",
    "172.16.*.*",
  ],
};

export default nextConfig;
