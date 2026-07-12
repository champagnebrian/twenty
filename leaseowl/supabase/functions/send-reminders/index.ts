import { errorResponse, handleOptions, jsonResponse } from '../_shared/cors.ts';
import { createServiceRoleClient } from '../_shared/auth.ts';

// Invoked by pg_cron (daily) via net.http_post — NOT user-JWT authenticated.
// Auth is a shared secret header; reject anything without it.
//
// Local notifications on-device are the primary reminder channel (Phase 8);
// this email is the fallback for users who declined notification permission.
//
// pg_cron setup (run once in the SQL editor, after deploying this function):
//   select cron.schedule(
//     'leaseowl-send-reminders', '0 14 * * *',
//     $$select net.http_post(
//         url := 'https://<project-ref>.supabase.co/functions/v1/send-reminders',
//         headers := jsonb_build_object('x-cron-secret', '<CRON_SECRET>')
//     )$$
//   );

const REMINDER_WINDOW_DAYS = 7;

type DeadlineRow = {
  id: string;
  user_id: string;
  label: string;
  due_on: string;
  state_code: string;
};

Deno.serve(async (req: Request): Promise<Response> => {
  const options = handleOptions(req);
  if (options !== null) return options;
  if (req.method !== 'POST') {
    return errorResponse(405, 'method_not_allowed', 'POST only');
  }

  const cronSecret = Deno.env.get('CRON_SECRET');
  if (cronSecret === undefined || req.headers.get('x-cron-secret') !== cronSecret) {
    return errorResponse(401, 'unauthorized', 'Invalid cron secret');
  }

  const resendKey = Deno.env.get('RESEND_API_KEY');
  if (resendKey === undefined) {
    return errorResponse(500, 'misconfigured', 'RESEND_API_KEY is not set');
  }

  const supabase = createServiceRoleClient();

  const today = new Date().toISOString().slice(0, 10);
  const windowEnd = new Date(Date.now() + REMINDER_WINDOW_DAYS * 86_400_000)
    .toISOString()
    .slice(0, 10);

  const { data: deadlines, error: deadlinesError } = await supabase
    .from('deadlines')
    .select('id, user_id, label, due_on, state_code')
    .gte('due_on', today)
    .lte('due_on', windowEnd)
    .is('reminder_sent_at', null);
  if (deadlinesError !== null) {
    return errorResponse(500, 'db_error', 'Could not load deadlines');
  }

  let sent = 0;
  let failed = 0;

  for (const deadline of (deadlines ?? []) as DeadlineRow[]) {
    // Email comes straight from auth.users — Supabase Auth owns it, no sync
    // webhook needed (this is one of the reasons the stack dropped Clerk).
    const { data: userData, error: userError } = await supabase.auth.admin.getUserById(
      deadline.user_id,
    );
    const email = userData?.user?.email;
    if (userError !== null || email === undefined || email === null) {
      failed += 1;
      continue;
    }

    const dueDate = new Date(`${deadline.due_on}T00:00:00Z`).toLocaleDateString('en-US', {
      timeZone: 'UTC',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

    try {
      const response = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${resendKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from: 'LeaseOwl <reminders@leaseowl.app>',
          to: [email],
          subject: `Upcoming deadline: ${deadline.label}`,
          text: [
            `You have an upcoming deadline in LeaseOwl:`,
            ``,
            `${deadline.label} — due ${dueDate} (${deadline.state_code})`,
            ``,
            `Open LeaseOwl for details.`,
            ``,
            `LeaseOwl provides legal information, not legal advice.`,
          ].join('\n'),
        }),
      });
      if (!response.ok) {
        throw new Error(`Resend HTTP ${response.status}`);
      }
      await supabase
        .from('deadlines')
        .update({ reminder_sent_at: new Date().toISOString() })
        .eq('id', deadline.id);
      sent += 1;
    } catch (error) {
      console.error(`send-reminders: failed for deadline ${deadline.id}`, error);
      failed += 1;
    }
  }

  return jsonResponse({ sent, failed });
});
