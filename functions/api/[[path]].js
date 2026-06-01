/**
 * Cloudflare Pages Functions - 全局API代理
 * 匹配 /api/* 路径，转发到阿里云 ECS 后端
 * 前端调用 /api/funds → 代理到 /api/v1/funds
 */
const BACKEND = "https://api.jinkuaicha.com";

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const pathname = url.pathname;

  if (!pathname.startsWith("/api/")) {
    return context.next();
  }

  if (context.request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "86400",
      },
    });
  }

  try {
    // /api/v1/funds → /api/v1/funds（直接转发）
    // /api/funds → /api/v1/funds（兼容旧路径）
    const v1Path = pathname.startsWith("/api/v1/")
      ? pathname
      : pathname.replace(/^\/api\//, "/api/v1/");
    const target = BACKEND + v1Path + url.search;
    const init = {
      method: context.request.method,
      headers: {
        "User-Agent": "CF-Pages-Proxy/1.0",
        "Accept": "application/json",
      },
    };
    // POST/PUT 请求转发 body
    if (context.request.method !== "GET" && context.request.method !== "HEAD") {
      init.body = await context.request.text();
      init.headers["Content-Type"] = context.request.headers.get("Content-Type") || "application/json";
    }
    // 转发 Authorization header
    const auth = context.request.headers.get("Authorization");
    if (auth) {
      init.headers["Authorization"] = auth;
    }

    const response = await fetch(target, init);
    const ct = response.headers.get("Content-Type") || "application/json";
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        "Content-Type": ct,
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Cache-Control": "no-store",
        "X-Proxy-From": "CF-Pages-Functions",
      },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ code: 503, message: "Backend unreachable: " + err.message }),
      {
        status: 503,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
        },
      }
    );
  }
}
