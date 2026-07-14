import { createClient, type SupabaseClient } from 'npm:@supabase/supabase-js@2';

// Verifies the caller's Supabase access token and returns their user id.
// The user id is ALWAYS derived from the JWT — never from the request body.
export const getUserIdFromRequest = async (
  req: Request,
): Promise<string | null> => {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return null;
  }

  const anonClient = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_ANON_KEY')!,
    { global: { headers: { Authorization: authHeader } } },
  );

  const {
    data: { user },
    error,
  } = await anonClient.auth.getUser();

  if (error !== null || user === null) {
    return null;
  }

  return user.id;
};

// Service-role client for writes that bypass RLS (flag/letter inserts,
// deletion cascade). Never expose this client's results unfiltered — every
// query it runs must be scoped by the JWT-derived user id.
export const createServiceRoleClient = (): SupabaseClient =>
  createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );
