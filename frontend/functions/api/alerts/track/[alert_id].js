const BACKEND_URL_ENV = "REACT_APP_BACKEND_URL";

function backendOriginFromEnv(env) {
  const raw = env?.[BACKEND_URL_ENV];
  if (!raw) {
    return null;
  }

  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:") {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

export async function onRequestGet(context) {
  const backendOrigin = backendOriginFromEnv(context.env);
  if (!backendOrigin) {
    return new Response("Backend origin is not configured", { status: 500 });
  }

  const incomingUrl = new URL(context.request.url);
  const upstreamUrl = new URL(
    `${incomingUrl.pathname}${incomingUrl.search}`,
    backendOrigin,
  );

  try {
    return await fetch(upstreamUrl.toString(), {
      method: "GET",
      redirect: "manual",
    });
  } catch {
    return new Response("Alert tracking backend unavailable", { status: 502 });
  }
}
