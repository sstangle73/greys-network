/**
 * Report relay
 * ============
 * A Cloudflare Worker that turns a form POST into a GitLab issue.
 *
 * WHY THIS EXISTS AS A SEPARATE SERVICE
 *   The chart is a static page on GitLab Pages. A static page cannot keep a
 *   secret -- anything shipped in it is public, and scrapers find tokens fast.
 *   So the token lives here, in a worker secret, and the browser never sees it.
 *
 * WHAT IT IS NOT
 *   This is not a general-purpose proxy. It files issues in exactly one
 *   project, with a fixed label, and it will not forward anything else.
 *
 * DEPLOY
 *   1. Create a GitLab *project* access token on sstangle73/greys-network with
 *      scope `api` and the Reporter role. Project tokens are scoped to one
 *      project, so a leak cannot touch anything else you own.
 *   2. wrangler secret put GITLAB_TOKEN
 *   3. wrangler deploy
 *   4. Set RELAY in build_visualization.py to the worker URL and rebuild.
 *
 * ROTATE the token if the worker URL ever ends up somewhere it should not be.
 */

const PROJECT_ID = "85043144";            // sstangle73/greys-network
const LABEL = "from-the-chart";
const MAX_BODY = 6000;                     // generous for a report, hostile to a dump
const WINDOW_SECONDS = 3600;
const MAX_PER_WINDOW = 5;                  // per IP per hour

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    const allowed = (env.ALLOWED_ORIGIN || "").split(",").map(s => s.trim()).filter(Boolean);
    const corsOrigin = allowed.includes(origin) ? origin : allowed[0] || "";

    const cors = {
      "Access-Control-Allow-Origin": corsOrigin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin",
    };

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method !== "POST") return json({ error: "POST only" }, 405, cors);
    if (allowed.length && !allowed.includes(origin)) {
      return json({ error: "origin not allowed" }, 403, cors);
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return json({ error: "expected JSON" }, 400, cors);
    }

    // Honeypot. Return 200 rather than an error: telling a bot it failed only
    // teaches it to try again differently.
    if (payload.website) return json({ ok: true }, 200, cors);

    const title = String(payload.title || "").trim().slice(0, 160);
    const body = String(payload.body || "").trim().slice(0, MAX_BODY);
    if (!title || body.length < 12) {
      return json({ error: "title and a real description are required" }, 400, cors);
    }

    // Rate limit per IP. KV is optional -- without it the worker still works,
    // it just stops counting, which is a deliberate fail-open: a broken limiter
    // should not silence genuine reports.
    if (env.RATE) {
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      const key = `rl:${ip}`;
      const seen = parseInt((await env.RATE.get(key)) || "0", 10);
      if (seen >= MAX_PER_WINDOW) {
        return json({ error: "too many reports from here for now" }, 429, cors);
      }
      ctx.waitUntil(env.RATE.put(key, String(seen + 1), { expirationTtl: WINDOW_SECONDS }));
    }

    const res = await fetch(
      `https://gitlab.com/api/v4/projects/${PROJECT_ID}/issues`,
      {
        method: "POST",
        headers: {
          "PRIVATE-TOKEN": env.GITLAB_TOKEN,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          title,
          description: `${body}\n\n_Filed from the chart via the report form._`,
          labels: LABEL,
        }),
      });

    if (!res.ok) {
      // Never surface GitLab's response: it can contain project detail the
      // reporter has no business seeing.
      return json({ error: "could not file the report" }, 502, cors);
    }
    return json({ ok: true }, 200, cors);
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...cors },
  });
}
