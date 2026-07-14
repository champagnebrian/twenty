// Fixed-window rate limiting on Upstash Redis (REST API).
// Fixed window (vs sliding) is deliberate: both AI operations are capped at
// 5/hour, so boundary bursts don't matter and the implementation stays small.
//
// FAIL CLOSED: if Upstash is unreachable, the request is denied — a Redis
// outage must not turn into an unmetered Claude bill.

type RateLimitResult =
  | { allowed: true }
  | { allowed: false; retryAfterSeconds: number };

export const checkRateLimit = async (
  operation: string,
  userId: string,
  limit: number,
  windowSeconds: number,
): Promise<RateLimitResult> => {
  const url = Deno.env.get('UPSTASH_REDIS_REST_URL');
  const token = Deno.env.get('UPSTASH_REDIS_REST_TOKEN');
  if (url === undefined || token === undefined) {
    console.error('ratelimit: Upstash credentials missing — failing closed');
    return { allowed: false, retryAfterSeconds: windowSeconds };
  }

  const window = Math.floor(Date.now() / 1000 / windowSeconds);
  const key = `ratelimit:${operation}:${userId}:${window}`;
  const windowEndsAt = (window + 1) * windowSeconds;
  const retryAfterSeconds = Math.max(
    1,
    windowEndsAt - Math.floor(Date.now() / 1000),
  );

  try {
    // Pipeline: INCR the counter, set the expiry on first hit.
    const response = await fetch(`${url}/pipeline`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify([
        ['INCR', key],
        ['EXPIRE', key, String(windowSeconds), 'NX'],
      ]),
    });

    if (!response.ok) {
      console.error(`ratelimit: Upstash HTTP ${response.status} — failing closed`);
      return { allowed: false, retryAfterSeconds };
    }

    const results = (await response.json()) as Array<{ result: unknown }>;
    const count = Number(results[0]?.result);

    if (!Number.isFinite(count)) {
      console.error('ratelimit: unexpected Upstash response — failing closed');
      return { allowed: false, retryAfterSeconds };
    }

    return count <= limit ? { allowed: true } : { allowed: false, retryAfterSeconds };
  } catch (error) {
    console.error('ratelimit: Upstash unreachable — failing closed', error);
    return { allowed: false, retryAfterSeconds };
  }
};
