/**
 * Cloudflare Pages Functions - 全局API代理
 * 匹配所有非静态文件的路径，转发到Railway后端
 * 
 * 解决中国网络访问Railway美国节点被阻断的问题
 * 浏览器 → CF Pages（同源）→ Railway后端
 */

const RAILWAY = "https://lof-premium-tracker-production.up.railway.app";

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const pathname = url.pathname;

  // /api/* 和 /health 都转发到Railway
  const isApi = pathname.startsWith("/api/");
  const isHealth = pathname === "/health";

  if (!isApi && !isHealth) {
    // 让其他路径继续走静态文件
    return context.next();
  }

  const target = RAILWAY + pathname + url.search;

  if (context.request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "86400",
      },
    });
  }

  try {
    const response = await fetch(target, {
      headers: {
        "User-Agent": "CF-Pages-Proxy/1.0",
        "Accept": "application/json",
      },
    });

    const ct = response.headers.get("Content-Type") || "application/json";
    const body = await response.text();

    return new Response(body, {
      status: response.status,
      headers: {
        "Content-Type": ct,
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control": "no-store",
        "X-Proxy-From": "CF-Pages-Functions",
      },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ code: 503, message: "Railway unreachable: " + err.message }),
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
