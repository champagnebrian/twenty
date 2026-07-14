import { errorResponse, handleOptions } from '../_shared/cors.ts';
import { createServiceRoleClient, getUserIdFromRequest } from '../_shared/auth.ts';

// Apple Guideline 5.1.1(v): in-app account deletion must fully work.
//
// Deletion order is load-bearing — the auth record goes LAST so a partial
// failure never strands data behind a deleted login. Every step is idempotent
// (deleting nothing succeeds), so the client can safely retry after a 5xx.
//
// Note: deleting the RevenueCat subscriber does NOT cancel an active App
// Store subscription; the client must tell the user to cancel in Settings.

const deleteStorageObjects = async (
  supabase: ReturnType<typeof createServiceRoleClient>,
  userId: string,
): Promise<void> => {
  const batchSize = 100;
  for (;;) {
    const { data: objects, error } = await supabase.storage
      .from('leases')
      .list(userId, { limit: batchSize });
    if (error !== null) {
      throw new Error(`storage list failed: ${error.message}`);
    }
    if (objects === null || objects.length === 0) {
      return;
    }
    const paths = objects.map((object) => `${userId}/${object.name}`);
    const { error: removeError } = await supabase.storage.from('leases').remove(paths);
    if (removeError !== null) {
      throw new Error(`storage remove failed: ${removeError.message}`);
    }
    if (objects.length < batchSize) {
      return;
    }
  }
};

const deleteRevenueCatSubscriber = async (userId: string): Promise<void> => {
  const secretKey = Deno.env.get('REVENUECAT_SECRET_KEY');
  if (secretKey === undefined) {
    // Deletion must not be blocked by a missing optional integration,
    // but the gap must be visible in logs.
    console.error('delete-account: REVENUECAT_SECRET_KEY missing — skipping RevenueCat deletion');
    return;
  }
  const response = await fetch(
    `https://api.revenuecat.com/v1/subscribers/${encodeURIComponent(userId)}`,
    { method: 'DELETE', headers: { Authorization: `Bearer ${secretKey}` } },
  );
  // 404 = subscriber never existed; that's success for a deletion.
  if (!response.ok && response.status !== 404) {
    throw new Error(`RevenueCat deletion failed: HTTP ${response.status}`);
  }
};

Deno.serve(async (req: Request): Promise<Response> => {
  const options = handleOptions(req);
  if (options !== null) return options;
  if (req.method !== 'POST') {
    return errorResponse(405, 'method_not_allowed', 'POST only');
  }

  const userId = await getUserIdFromRequest(req);
  if (userId === null) {
    return errorResponse(401, 'unauthorized', 'Missing or invalid access token');
  }

  const supabase = createServiceRoleClient();

  try {
    // 1. Storage objects (the lease PDFs — the most sensitive data).
    await deleteStorageObjects(supabase, userId);

    // 2. RevenueCat subscriber.
    await deleteRevenueCatSubscriber(userId);

    // 3. The users row — documents/flags/letters/deadlines cascade via FK.
    const { error: rowError } = await supabase.from('users').delete().eq('id', userId);
    if (rowError !== null) {
      throw new Error(`users row deletion failed: ${rowError.message}`);
    }

    // 4. The auth record, last.
    const { error: authError } = await supabase.auth.admin.deleteUser(userId);
    if (authError !== null) {
      throw new Error(`auth user deletion failed: ${authError.message}`);
    }
  } catch (error) {
    console.error('delete-account failed', error instanceof Error ? error.message : 'unknown');
    return errorResponse(500, 'deletion_failed', 'Account deletion failed — please try again');
  }

  return new Response(null, { status: 204 });
});
