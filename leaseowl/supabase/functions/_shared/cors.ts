// Native app doesn't need CORS, but answering OPTIONS keeps web-based
// testing (curl from a browser console, Supabase Studio) working.
export const corsHeaders: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers':
    'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

export const handleOptions = (req: Request): Response | null =>
  req.method === 'OPTIONS' ? new Response(null, { headers: corsHeaders }) : null;

export const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });

export const errorResponse = (
  status: number,
  code: string,
  message: string,
  extra: Record<string, unknown> = {},
): Response => jsonResponse({ error: { code, message, ...extra } }, status);
